"""Pre-build step: parse ONT España balance PDF table extracts -> ont_national.csv.

Reads the page_*_table_*.csv files emitted by `python -m ingest.ont_spain` from
the latest ont_spain bronze snapshot and produces ont_national.csv with columns:
  year, total_transplants, deceased_donors, living_donors

PDF structure (BALANCE-ONT annual report)
-----------------------------------------
The ONT PDF contains two relevant table types:

1. **Organ CCAA tables** (one per organ: kidney, liver, heart, lung, pancreas,
   intestine). Structure: first column = autonomous community names, remaining
   columns = years (2020-2024). Key rows:
     - "Total del Estado"   → national transplant total for that organ
     - "Trasplante* Vivo"   → living-donor transplants for that organ
   Strategy: identify by [CC.AA label | year | year | ...] header pattern +
   presence of "Total del Estado" row; sum across ALL matching tables.

2. **Donor comparative tables** (appear twice in the PDF, pages ~7 and ~31).
   Structure: years as multi-cell headers ("Año 2023", "Año 2024"), rows per
   autonomous community, "TOTAL DEL ESTADO" row with national deceased-donor
   count. Only 2023-2024 covered; earlier years will be NULL.

Failure modes
-------------
- No completed snapshot found  → exit 1 (run `python -m ingest.ont_spain` first)
- No transplant data extracted → exit 1 with a diagnostic listing of candidate
  tables so keyword/heuristic logic can be adjusted for a new PDF layout
"""

from __future__ import annotations

import csv
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
RAW_ROOT = REPO_ROOT / "data" / "raw" / "ont_spain"

# Matches "Año 2023", "AÑO 2024", "Año2023", etc. in donor comparative tables
_YEAR_LABEL_RE = re.compile(r"\bA[Nn\xf1][Oo]\s*(20\d{2})\b", re.IGNORECASE)


def _norm(text: str) -> str:
    """Lowercase, strip accents for keyword matching."""
    return (
        text.lower()
        .replace("\xe1", "a").replace("\xe9", "e").replace("\xed", "i")
        .replace("\xf3", "o").replace("\xfa", "u").replace("\xf1", "n")
        .strip()
    )


def _first_line(text: str) -> str:
    """Return only the first line of a possibly multi-line cell value."""
    return text.split("\n")[0].split("\r")[0]


def _total_line(text: str) -> str:
    """Extract the transplant total from a 'Total del Estado' cell.

    Most organ tables have simple single-line values or two-line cells where the
    first line is the total and the second is a parenthetical sub-count (e.g. lung:
    '623\n(557)' means 623 total, 557 from deceased donors).

    The intestine table is the exception: pdfplumber merges the Int.A sub-row, the MV
    sub-row, and sometimes a grand-total row into one cell. When 3+ non-empty lines are
    present the last line is the grand total ('1\n6\n7' -> 7). When only 2 lines are
    present the first line is still the total ('4\n4', '5\n5').
    """
    lines = [ln.strip() for ln in text.replace("\r", "\n").split("\n") if ln.strip()]
    if len(lines) >= 3:
        return lines[-1]
    return lines[0] if lines else ""


def _parse_int(val: str) -> int | None:
    """Parse integers in Spanish format: '2.346' -> 2346. Ignores parenthetical annotations."""
    cleaned = re.sub(r"[\s.,]", "", _first_line(val).strip())
    if not cleaned or cleaned in {"-", "—", "n/d", "nd"}:
        return None
    try:
        n = int(cleaned)
        return n if n >= 0 else None
    except ValueError:
        return None


def _is_year(val: str) -> bool:
    try:
        return 1990 <= int(_first_line(val).strip()) <= 2030
    except ValueError:
        return False


def _load_csv(path: Path) -> list[list[str]]:
    with path.open(encoding="utf-8", errors="replace") as fh:
        return list(csv.reader(fh))


def _classify(rows: list[list[str]]) -> str:
    """Return 'organ', 'donor', or 'other'."""
    if len(rows) < 2:
        return "other"

    # Donor comparative table: has "Año YYYY" label in the first few rows
    for row in rows[:3]:
        for cell in row:
            if _YEAR_LABEL_RE.search(cell):
                has_total = any(
                    r and "total" in _norm(r[0]) and "estado" in _norm(r[0])
                    for r in rows
                )
                if has_total:
                    return "donor"

    # Organ CCAA table: header has >=2 year-like values + has "Total del Estado" row
    header = rows[0]
    year_count = sum(1 for cell in header if _is_year(cell))
    if year_count >= 2:
        has_total = any(
            r and "total" in _norm(_first_line(r[0])) and "estado" in _norm(_first_line(r[0]))
            for r in rows
        )
        if has_total:
            return "organ"

    return "other"


def _extract_organ(rows: list[list[str]]) -> tuple[dict[int, int], dict[int, int]]:
    """Return (total_tx_by_year, living_tx_by_year) from one organ CCAA table."""
    header = rows[0]
    year_cols: dict[int, int] = {
        i: int(_first_line(cell).strip())
        for i, cell in enumerate(header)
        if _is_year(cell)
    }

    totals: dict[int, int] = {}
    living: dict[int, int] = {}

    for row in rows[1:]:
        if not row:
            continue
        label = _norm(_first_line(row[0]))

        if "total" in label and "estado" in label:
            for col_idx, yr in year_cols.items():
                if col_idx < len(row):
                    val = _parse_int(_total_line(row[col_idx]))
                    if val is not None and val > 0:
                        totals[yr] = val

        elif "vivo" in label:
            for col_idx, yr in year_cols.items():
                if col_idx < len(row):
                    val = _parse_int(row[col_idx])
                    if val is not None and val > 0:
                        living[yr] = living.get(yr, 0) + val

    return totals, living


def _extract_deceased(rows: list[list[str]]) -> dict[int, int]:
    """Return {year: deceased_donors} from a donor comparative table (2 years only)."""
    year_to_col: dict[int, int] = {}
    for row in rows[:3]:
        for col_idx, cell in enumerate(row):
            m = _YEAR_LABEL_RE.search(cell)
            if m:
                year_to_col[int(m.group(1))] = col_idx

    if not year_to_col:
        return {}

    for row in rows:
        if not row:
            continue
        label = _norm(row[0])
        if "total" in label and "estado" in label:
            result = {}
            for yr, col_idx in year_to_col.items():
                if col_idx < len(row):
                    val = _parse_int(row[col_idx])
                    # Sanity check: Spain has ~1,500-3,000 deceased donors/year
                    if val is not None and 500 <= val <= 5000:
                        result[yr] = val
            if result:
                return result
    return {}


def _latest_snapshot() -> Path | None:
    if not RAW_ROOT.exists():
        return None
    candidates = sorted(
        d for d in RAW_ROOT.iterdir()
        if d.is_dir() and (d / "meta.json").exists()
    )
    return candidates[-1] if candidates else None


def main() -> int:
    snap = _latest_snapshot()
    if snap is None:
        print(f"ERROR: no completed ont_spain snapshot under {RAW_ROOT}", file=sys.stderr)
        print("Run: python -m ingest.ont_spain", file=sys.stderr)
        return 1

    csv_files = sorted(snap.glob("page_*_table_*.csv"))
    if not csv_files:
        print(f"ERROR: no page_*_table_*.csv in {snap}", file=sys.stderr)
        return 1

    print(f"ont_spain snapshot: {snap.name}, {len(csv_files)} tables", file=sys.stderr)

    total_tx: dict[int, int] = {}
    living_tx: dict[int, int] = {}
    deceased_tx: dict[int, int] = {}
    organ_tables_found: list[str] = []

    for csv_path in csv_files:
        rows = _load_csv(csv_path)
        kind = _classify(rows)

        if kind == "organ":
            organ_tables_found.append(csv_path.name)
            totals, living = _extract_organ(rows)
            if totals:
                print(
                    f"  organ table {csv_path.name}: years {sorted(totals)}, "
                    f"max={max(totals.values())}",
                    file=sys.stderr,
                )
                for yr, val in totals.items():
                    total_tx[yr] = total_tx.get(yr, 0) + val
                for yr, val in living.items():
                    living_tx[yr] = living_tx.get(yr, 0) + val

        elif kind == "donor":
            dec = _extract_deceased(rows)
            if dec:
                print(f"  donor table {csv_path.name}: deceased={dec}", file=sys.stderr)
                for yr, val in dec.items():
                    if yr not in deceased_tx:  # avoid double-counting duplicate pages
                        deceased_tx[yr] = val

    if not total_tx:
        print(
            "ERROR: could not extract transplant data.\n"
            f"Organ table candidates: {organ_tables_found or 'none found'}\n"
            "Inspect extracted CSVs and adjust _classify() heuristics.",
            file=sys.stderr,
        )
        return 1

    out_path = snap / "ont_national.csv"
    years = sorted(total_tx)
    with out_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["year", "total_transplants", "deceased_donors", "living_donors"])
        for yr in years:
            writer.writerow([
                yr,
                total_tx.get(yr),
                deceased_tx.get(yr),
                living_tx.get(yr),
            ])

    print(f"wrote {len(years)} rows -> {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
