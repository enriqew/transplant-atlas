"""Pre-build step: parse Scandiatransplant annual XLSX -> sctp_national.csv.

Reads the XLSX downloaded by `python -m ingest.scandiatransplant` from the
latest Scandiatransplant bronze snapshot and produces sctp_national.csv with
columns: year, country_iso3, country_name, total_transplants, deceased_donors,
living_donors.

XLSX structure
--------------
One sheet per year (sheet name = "2025", "2024", etc.).  The column layout has
changed multiple times as new transplant centers joined Scandiatransplant:

  • Pre-2007: sub-center columns for Denmark/Sweden; country totals at variable
    column positions; labels in Danish/Scandinavian.
  • 2007–2019: country total columns at fixed positions; labels mixed.
  • 2020+: modern English labels; Estonia column added.

To handle this, the parser:
  1. Detects the "country header row" dynamically (the row containing ≥3
     recognized country name tokens).
  2. Maps column index → ISO3 for each year.
  3. Accumulates data rows by matching row labels against known label sets
     (both modern English and old-style Scandinavian/English variants).

Coverage: DNK, SWE, NOR, FIN, ISL, EST — 1990 to present.
Sheets pre-dating reliable structure (< _MIN_YEAR) are skipped.

Failure modes
-------------
- No completed snapshot     → exit 1
- XLSX not found            → exit 1
- No country columns found  → that sheet is skipped with a warning
- No transplant rows found  → that sheet is skipped with a warning
"""

from __future__ import annotations

import csv
import logging
import sys
from pathlib import Path

import openpyxl

logging.basicConfig(
    level="INFO",
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
    stream=sys.stderr,
)
log = logging.getLogger("analyses.scandiatransplant_xlsx_to_csv")

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
RAW_ROOT = REPO_ROOT / "data" / "raw"

# Pre-2000 sheets have blank "Total" rows (data only in per-organ sub-rows with
# labels that don't match modern label conventions). Reliable from 2000 onward.
_MIN_YEAR = 2000

# All known country name variants across all sheet versions (case-insensitive key)
_COUNTRY_NAME_MAP: dict[str, str] = {}
for _iso3, _names in {
    "DNK": ["Denmark", "Danmark"],
    "SWE": ["Sweden", "Sverige"],
    "NOR": ["Norway", "Norge"],
    "FIN": ["Finland"],
    "ISL": ["Iceland", "Island", "ísland"],
    "EST": ["Estonia"],
}.items():
    for _n in _names:
        _COUNTRY_NAME_MAP[_n.lower()] = _iso3

_COUNTRY_DISPLAY: dict[str, str] = {
    "DNK": "Denmark",
    "SWE": "Sweden",
    "NOR": "Norway",
    "FIN": "Finland",
    "ISL": "Iceland",
    "EST": "Estonia",
}

# Row labels that contribute to total_transplants (solid organ + islets)
# Includes both modern English and old-style label variants.
_TX_ROW_LABELS: set[str] = {
    "Total Kidney",
    "Total Liver",
    "Total Heart",
    "Total Lungs",
    "Pancreas",
    "Islet",
    "Islet Patients",
    "Intestine",
}
_TX_ROW_LABELS_LOWER = {s.lower() for s in _TX_ROW_LABELS}

# Row labels for deceased donors (multiple naming conventions across years)
_DECEASED_LABELS_LOWER: set[str] = {
    "total utilized deceased donors",
    "realized deceased donors",
    "utilized deceased donors",
    "realized donors",       # 2004-2009 label
    "cadaveric donors",      # 2000-2003 label
}

# Row labels for living donors
_LIVING_LABELS_LOWER: set[str] = {
    "living donor kidney",
    "living donor liver",
    "living kidney",   # old-style label
    "living liver",    # old-style label
}


def _latest_snapshot_dir() -> Path:
    sctp_dir = RAW_ROOT / "scandiatransplant"
    if not sctp_dir.exists():
        log.error("no scandiatransplant snapshot directory at %s", sctp_dir)
        sys.exit(1)

    candidates = sorted(
        (d for d in sctp_dir.iterdir() if d.is_dir() and (d / "meta.json").exists()),
        key=lambda d: d.name,
        reverse=True,
    )
    if not candidates:
        log.error("no completed scandiatransplant snapshots (no meta.json found)")
        sys.exit(1)

    return candidates[0]


def _find_xlsx(snapshot_dir: Path) -> Path:
    xlsx_files = list(snapshot_dir.glob("*.xlsx"))
    if not xlsx_files:
        log.error("no XLSX file found in %s", snapshot_dir)
        sys.exit(1)
    return xlsx_files[0]


def _int_or_none(value) -> int | None:
    """Convert a cell value to int, returning None for blank/non-numeric.

    Handles old-style annotations like "68 (37)" by taking only the leading
    numeric token before any parenthetical.
    """
    if value is None:
        return None
    s = str(value).strip()
    if not s or s in ("-", ""):
        return None
    # Take only the first whitespace-separated token (handles "68 (37)")
    token = s.split()[0].replace(",", "").replace(" ", "")
    try:
        return int(float(token))
    except (ValueError, TypeError):
        return None


def _find_country_columns(rows: list) -> dict[str, int]:
    """Scan all rows to find the header row with ≥3 country name matches.

    Returns a dict mapping ISO3 → column index for that year's layout.
    An empty dict means the sheet layout is unrecognised.
    """
    for row in rows:
        cols: dict[str, int] = {}
        for ci, cell in enumerate(row):
            if cell is None:
                continue
            name = str(cell).strip().lower()
            iso3 = _COUNTRY_NAME_MAP.get(name)
            if iso3 and iso3 not in cols:
                cols[iso3] = ci
        if len(cols) >= 3:
            return cols
    return {}


def _parse_year_sheet(sheet, year: int) -> list[dict]:
    """Extract per-country transplant/donor data from a single year sheet."""
    rows = list(sheet.iter_rows(values_only=True))

    country_cols = _find_country_columns(rows)
    if not country_cols:
        log.warning("year %d: no country header row found — skipping sheet", year)
        return []

    tx_totals: dict[str, int] = {iso3: 0 for iso3 in country_cols}
    deceased: dict[str, int | None] = {iso3: None for iso3 in country_cols}
    living_totals: dict[str, int] = {iso3: 0 for iso3 in country_cols}

    tx_rows_seen = 0
    deceased_found = False

    for row in rows:
        if not row or row[0] is None:
            continue
        label_lower = str(row[0]).strip().lower()

        if label_lower in _TX_ROW_LABELS_LOWER:
            tx_rows_seen += 1
            for iso3, col in country_cols.items():
                val = _int_or_none(row[col] if col < len(row) else None)
                if val is not None:
                    tx_totals[iso3] += val

        elif label_lower in _DECEASED_LABELS_LOWER and not deceased_found:
            deceased_found = True
            for iso3, col in country_cols.items():
                val = _int_or_none(row[col] if col < len(row) else None)
                deceased[iso3] = val

        elif label_lower in _LIVING_LABELS_LOWER:
            for iso3, col in country_cols.items():
                val = _int_or_none(row[col] if col < len(row) else None)
                if val is not None:
                    living_totals[iso3] += val

    if tx_rows_seen == 0:
        log.warning("year %d: no transplant rows matched — sheet layout may have changed", year)
        return []

    results = []
    for iso3 in country_cols:
        total_tx = tx_totals[iso3] if tx_totals[iso3] > 0 else None
        dec = deceased.get(iso3)
        living = living_totals[iso3] if living_totals[iso3] > 0 else None

        if total_tx is None and dec is None and living is None:
            continue

        results.append(
            {
                "year": year,
                "country_iso3": iso3,
                "country_name": _COUNTRY_DISPLAY[iso3],
                "total_transplants": total_tx,
                "deceased_donors": dec,
                "living_donors": living,
            }
        )

    return results


def main() -> int:
    snapshot_dir = _latest_snapshot_dir()
    xlsx_path = _find_xlsx(snapshot_dir)
    log.info("reading %s", xlsx_path)

    wb = openpyxl.load_workbook(xlsx_path, read_only=True, data_only=True)

    all_rows: list[dict] = []
    skipped_sheets: list[str] = []

    for sheet_name in wb.sheetnames:
        try:
            year = int(sheet_name.strip())
        except ValueError:
            skipped_sheets.append(sheet_name)
            continue

        if year < _MIN_YEAR:
            continue

        sheet = wb[sheet_name]
        year_rows = _parse_year_sheet(sheet, year)
        all_rows.extend(year_rows)
        log.info("year %d: %d country rows", year, len(year_rows))

    wb.close()

    if skipped_sheets:
        log.info("skipped non-year sheets: %s", skipped_sheets)

    if not all_rows:
        log.error("no data extracted — check XLSX sheet layout")
        return 1

    out_path = snapshot_dir / "sctp_national.csv"
    fieldnames = [
        "year", "country_iso3", "country_name",
        "total_transplants", "deceased_donors", "living_donors",
    ]

    with out_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(sorted(all_rows, key=lambda r: (r["country_iso3"], r["year"])))

    log.info("wrote %d rows to %s", len(all_rows), out_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
