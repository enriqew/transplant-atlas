"""Pre-build step: parse Eurotransplant Statistics HTML reports -> et_national.csv.

Reads the two HTML files downloaded by `python -m ingest.eurotransplant` from the
latest eurotransplant bronze snapshot and produces et_national.csv with columns:
  year, country_iso3, country_name, total_transplants, deceased_donors, living_donors

Source reports
--------------
1. deceased_donors.html (report 11034)
   "Deceased donors used in Eurotransplant, by year, by donor country"
   HTML table structure (nested inside layout table):
     Row 0: title
     Row 1: ['', 'Donors used', '2016', '2017', ..., '2025']   <- year headers at col 2+
     Row 2+: ['ET_CODE', 'Country', count, count, ...]          <- col 1 = name, col 2+ = values
   Parsed via _parse_deceased_donors().

2. transplants_pmp.html (report 10821-33157)
   "Transplants per million population, by year, by country, by donor type"
   HTML table structure (nested inside layout table):
     Row 0: title
     Row 1: ['', 'Donor type', '2016', '2017', ..., '2025']    <- year headers at col 2+
     Per country (3 rows):
       ['Country', 'Deceased', pmp, pmp, ...]                   <- deceased row
       ['',        'Living',   pmp, pmp, ...]                   <- living row
       ['Country', '',         pmp, pmp, ...]                   <- total row (dtype empty)
   Parsed via _parse_transplants_pmp().

Methodology
-----------
`deceased_donors` is taken directly from report 11034 (exact integer).
`total_transplants` and `living_donors` are back-calculated from pmp rates in
report 10821-33157 multiplied by World Bank population (rounded to integer).
This introduces ±1-5% rounding error vs. ET's internal exact counts.

Coverage: AUT, BEL, HRV, DEU, HUN, NLD, SVN (2016 onward).
Luxembourg (LUX) is excluded; IRODaT covers it at lower priority.

Failure modes
-------------
- No completed snapshot              -> exit 1
- Deceased donors table not found    -> exit 1 with diagnostic
- PMP table not found                -> exit 1 with diagnostic
- No population data for a country   -> that row gets NULL pmp-derived fields
"""

from __future__ import annotations

import csv
import json
import re
import sys
from html.parser import HTMLParser
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
RAW_ROOT = REPO_ROOT / "data" / "raw" / "eurotransplant"
POP_ROOT = REPO_ROOT / "data" / "raw" / "population_world"

# ET country names (lowercase, as they appear in HTML) -> ISO 3166-1 alpha-3
_ET_NAME_TO_ISO3: dict[str, str] = {
    "austria": "AUT",
    "belgium": "BEL",
    "croatia": "HRV",
    "germany": "DEU",
    "hungary": "HUN",
    "netherlands": "NLD",
    "slovenia": "SVN",
}

_ISO3_TO_NAME: dict[str, str] = {
    "AUT": "Austria",
    "BEL": "Belgium",
    "HRV": "Croatia",
    "DEU": "Germany",
    "HUN": "Hungary",
    "NLD": "Netherlands",
    "SVN": "Slovenia",
}


# ---------------------------------------------------------------------------
# HTML table extractor (all depths)
# ---------------------------------------------------------------------------

class _RowExtractor(HTMLParser):
    """Flatten all HTML table cells into a single ordered list of rows.

    Both ET report pages embed their data table inside a layout table.
    Extracting rows at all nesting depths and then applying content-based
    filtering is simpler than tracking table depth boundaries.
    """

    def __init__(self) -> None:
        super().__init__()
        self._in_table = False
        self._cur_row: list[str] | None = None
        self._in_cell = False
        self._buf: list[str] = []
        self.rows: list[list[str]] = []

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag == "table":
            self._in_table = True
        elif tag == "tr" and self._in_table:
            self._cur_row = []
        elif tag in ("td", "th") and self._cur_row is not None:
            self._in_cell = True
            self._buf = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "tr" and self._cur_row is not None:
            row = self._cur_row
            if any(c.strip() for c in row):
                self.rows.append(row)
            self._cur_row = None
        elif tag in ("td", "th") and self._in_cell:
            if self._cur_row is not None:
                self._cur_row.append(" ".join(self._buf).strip())
            self._in_cell = False
            self._buf = []

    def handle_data(self, data: str) -> None:
        if self._in_cell:
            self._buf.append(data)


def _get_rows(html: str) -> list[list[str]]:
    parser = _RowExtractor()
    parser.feed(html)
    return parser.rows


# ---------------------------------------------------------------------------
# Value parsers
# ---------------------------------------------------------------------------

def _parse_int(val: str) -> int | None:
    cleaned = re.sub(r"[\s,.\xa0]", "", val.strip())
    if not cleaned or cleaned in {"-", "—", "n/d"}:
        return None
    try:
        n = int(cleaned)
        return n if n >= 0 else None
    except ValueError:
        return None


def _parse_float(val: str) -> float | None:
    cleaned = val.strip().replace("\xa0", "").replace(",", ".")
    if not cleaned or cleaned in {"-", "—"}:
        return None
    try:
        f = float(cleaned)
        return f if f >= 0 else None
    except ValueError:
        return None


def _is_year(val: str) -> bool:
    try:
        return 2010 <= int(val.strip()) <= 2030
    except ValueError:
        return False


# ---------------------------------------------------------------------------
# Report-specific parsers
# ---------------------------------------------------------------------------

def _parse_deceased_donors(html: str) -> dict[str, dict[int, int]]:
    """Parse report 11034. Returns {iso3: {year: deceased_donors}}.

    Expected row layout after flattening:
      header: ['', 'Donors used', '2016', ..., '2025']   (year cols at index 2+)
      data:   ['ET_CODE', 'CountryName', count, ...]      (name at index 1)
    """
    rows = _get_rows(html)

    # Find the header row: col[1] ~= 'donors used' and year-like values at col 2+
    header_idx = -1
    year_cols: dict[int, int] = {}
    for i, row in enumerate(rows):
        if len(row) < 4:
            continue
        label = row[1].strip().lower()
        if "donors" in label or "used" in label:
            tmp = {j: int(row[j].strip()) for j in range(2, len(row)) if _is_year(row[j])}
            if len(tmp) >= 5:
                year_cols = tmp
                header_idx = i
                break

    if not year_cols:
        return {}

    result: dict[str, dict[int, int]] = {}
    for row in rows[header_idx + 1:]:
        if len(row) < 3:
            continue
        name = row[1].strip().lower()
        iso3 = _ET_NAME_TO_ISO3.get(name)
        if iso3 is None:
            continue
        counts: dict[int, int] = {}
        for col_idx, yr in year_cols.items():
            if col_idx < len(row):
                val = _parse_int(row[col_idx])
                if val is not None:
                    counts[yr] = val
        if counts:
            result[iso3] = counts

    return result


def _parse_transplants_pmp(
    html: str,
) -> dict[str, dict[int, dict[str, float]]]:
    """Parse report 10821-33157. Returns {iso3: {year: {deceased, living, total}}}.

    Expected row layout after flattening:
      header:  ['', 'Donor type', '2016', ..., '2025']   (year cols at index 2+)
      deceased: ['Country', 'Deceased', pmp, ...]         (col 0 = name, col 1 = type)
      living:   ['',        'Living',   pmp, ...]         (col 0 empty)
      total:    ['Country', '',         pmp, ...]         (col 0 = name, col 1 empty)
    """
    rows = _get_rows(html)

    # Find header row: col[1] contains 'donor type' or similar, years at col 2+
    header_idx = -1
    year_cols: dict[int, int] = {}
    for i, row in enumerate(rows):
        if len(row) < 4:
            continue
        label = row[1].strip().lower()
        if "donor" in label or "type" in label:
            tmp = {j: int(row[j].strip()) for j in range(2, len(row)) if _is_year(row[j])}
            if len(tmp) >= 5:
                year_cols = tmp
                header_idx = i
                break

    if not year_cols:
        return {}

    result: dict[str, dict[int, dict[str, float]]] = {}
    current_iso3: str | None = None

    for row in rows[header_idx + 1:]:
        if len(row) < 3:
            continue
        col0 = row[0].strip()
        col1 = row[1].strip().lower()

        # Identify row type
        if col0 and col1 == "deceased":
            iso3 = _ET_NAME_TO_ISO3.get(col0.lower())
            if iso3 is None:
                current_iso3 = None
                continue
            current_iso3 = iso3
            dtype = "deceased"
        elif not col0 and col1 == "living":
            if current_iso3 is None:
                continue
            dtype = "living"
        elif col0 and not col1:
            # total row — confirm country matches
            iso3 = _ET_NAME_TO_ISO3.get(col0.lower())
            if iso3 is None or iso3 != current_iso3:
                current_iso3 = None
                continue
            dtype = "total"
        else:
            continue

        for col_idx, yr in year_cols.items():
            if col_idx < len(row):
                val = _parse_float(row[col_idx])
                if val is not None:
                    result.setdefault(current_iso3, {}).setdefault(yr, {})[dtype] = val

    return result


# ---------------------------------------------------------------------------
# Population loader
# ---------------------------------------------------------------------------

def _load_population() -> dict[str, dict[int, int]]:
    """Return {iso3: {year: population}} from latest World Bank NDJSON snapshot."""
    if not POP_ROOT.exists():
        print(f"ERROR: population data not found at {POP_ROOT}", file=sys.stderr)
        print("Run: python -m ingest.population_world", file=sys.stderr)
        sys.exit(1)

    snapshots = sorted(d for d in POP_ROOT.iterdir() if d.is_dir())
    if not snapshots:
        sys.exit(f"ERROR: no population snapshot under {POP_ROOT}")

    ndjson = snapshots[-1] / "sp.pop.totl.rows.ndjson"
    if not ndjson.exists():
        sys.exit(f"ERROR: missing {ndjson}; run wb_json_to_ndjson.py first")

    pop: dict[str, dict[int, int]] = {}
    with ndjson.open(encoding="utf-8") as fh:
        for line in fh:
            rec = json.loads(line)
            iso3 = rec.get("countryiso3code")
            date_str = rec.get("date")
            val = rec.get("value")
            if iso3 and date_str and val is not None:
                pop.setdefault(iso3, {})[int(date_str)] = int(val)
    return pop


def _get_population(pop: dict[str, dict[int, int]], iso3: str, year: int) -> int | None:
    """Return population for iso3/year; fall back to the nearest earlier year."""
    country_pop = pop.get(iso3)
    if not country_pop:
        return None
    if year in country_pop and country_pop[year] is not None:
        return country_pop[year]
    candidates = [y for y in country_pop if y <= year and country_pop[y] is not None]
    return country_pop[max(candidates)] if candidates else None


def _pmp_to_abs(pmp: float | None, population: int | None) -> int | None:
    if pmp is None or population is None:
        return None
    return round(pmp * population / 1_000_000)


# ---------------------------------------------------------------------------
# Snapshot discovery
# ---------------------------------------------------------------------------

def _latest_snapshot() -> Path | None:
    if not RAW_ROOT.exists():
        return None
    candidates = sorted(
        d for d in RAW_ROOT.iterdir()
        if d.is_dir() and (d / "meta.json").exists()
    )
    return candidates[-1] if candidates else None


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    snap = _latest_snapshot()
    if snap is None:
        print(f"ERROR: no completed eurotransplant snapshot under {RAW_ROOT}", file=sys.stderr)
        print("Run: python -m ingest.eurotransplant", file=sys.stderr)
        return 1

    deceased_html_path = snap / "deceased_donors.html"
    pmp_html_path = snap / "transplants_pmp.html"
    for p in (deceased_html_path, pmp_html_path):
        if not p.exists():
            print(f"ERROR: missing {p}", file=sys.stderr)
            return 1

    print(f"eurotransplant snapshot: {snap.name}", file=sys.stderr)

    deceased_html = deceased_html_path.read_text(encoding="utf-8", errors="replace")
    pmp_html = pmp_html_path.read_text(encoding="utf-8", errors="replace")

    deceased_by_iso3 = _parse_deceased_donors(deceased_html)
    if not deceased_by_iso3:
        print(
            "ERROR: could not parse deceased donors from deceased_donors.html.\n"
            "Inspect the HTML and adjust _parse_deceased_donors() heuristics.",
            file=sys.stderr,
        )
        return 1
    print(
        f"  deceased_donors: {len(deceased_by_iso3)} countries, "
        f"years {sorted(next(iter(deceased_by_iso3.values())))}",
        file=sys.stderr,
    )

    pmp_by_iso3 = _parse_transplants_pmp(pmp_html)
    if not pmp_by_iso3:
        print(
            "ERROR: could not parse transplants pmp from transplants_pmp.html.\n"
            "Inspect the HTML and adjust _parse_transplants_pmp() heuristics.",
            file=sys.stderr,
        )
        return 1
    print(
        f"  transplants_pmp: {len(pmp_by_iso3)} countries",
        file=sys.stderr,
    )

    population = _load_population()

    rows: list[dict] = []
    for iso3, year_data in sorted(pmp_by_iso3.items()):
        country_name = _ISO3_TO_NAME.get(iso3, iso3)
        for year in sorted(year_data):
            pmp = year_data[year]
            pop = _get_population(population, iso3, year)

            total_tx = _pmp_to_abs(pmp.get("total"), pop)
            living_tx = _pmp_to_abs(pmp.get("living"), pop)
            deceased_donors = deceased_by_iso3.get(iso3, {}).get(year)

            if total_tx is None:
                print(
                    f"  WARNING: {iso3} {year}: no population data — skipping",
                    file=sys.stderr,
                )
                continue

            rows.append({
                "year": year,
                "country_iso3": iso3,
                "country_name": country_name,
                "total_transplants": total_tx,
                "deceased_donors": deceased_donors,
                "living_donors": living_tx,
            })

    if not rows:
        print("ERROR: no rows produced.", file=sys.stderr)
        return 1

    out_path = snap / "et_national.csv"
    with out_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=["year", "country_iso3", "country_name",
                        "total_transplants", "deceased_donors", "living_donors"],
        )
        writer.writeheader()
        writer.writerows(rows)

    print(f"wrote {len(rows)} rows -> {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
