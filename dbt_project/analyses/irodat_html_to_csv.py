"""Pre-step for stg_irodat: convert IRODaT per-country HTML snapshots to a single CSV.

Reads all `country_*.html` files inside the latest data/raw/irodat/<date>/ snapshot
and emits `irodat_country_year.csv` in the same directory. The staging dbt model
reads that CSV via read_csv_auto.

Failure modes:
  - No HTML files found in the latest snapshot → exit non-zero
  - A specific HTML cannot be parsed → log warning, skip that country; never fabricate.
"""

from __future__ import annotations

import csv
import re
import sys
from html.parser import HTMLParser
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
RAW_ROOT = REPO_ROOT / "data" / "raw" / "irodat"


class _RowExtractor(HTMLParser):
    """Naive HTML table extractor. Captures every <tr>'s flattened text cells.

    The schema of the resulting CSV is (country_name, report_year, total_transplants,
    deceased_donors, living_donors). Heuristics:
      - First non-numeric cell on the page is taken as country_name.
      - Numeric rows with exactly the expected column count are kept.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._in_cell = False
        self._cell_chunks: list[str] = []
        self._row_cells: list[str] = []
        self.rows: list[list[str]] = []
        self.title: str | None = None
        self._in_h1 = False

    def handle_starttag(self, tag: str, attrs):
        if tag.lower() == "td":
            self._in_cell = True
            self._cell_chunks = []
        elif tag.lower() == "h1":
            self._in_h1 = True

    def handle_endtag(self, tag: str):
        tag_lower = tag.lower()
        if tag_lower == "td":
            self._row_cells.append("".join(self._cell_chunks).strip())
            self._in_cell = False
        elif tag_lower == "tr":
            if self._row_cells:
                self.rows.append(self._row_cells)
            self._row_cells = []
        elif tag_lower == "h1":
            self._in_h1 = False

    def handle_data(self, data: str):
        if self._in_cell:
            self._cell_chunks.append(data)
        elif self._in_h1 and self.title is None:
            cleaned = data.strip()
            if cleaned:
                self.title = cleaned


_INT_RE = re.compile(r"^-?\d{1,9}$")


def _to_int(value: str) -> int | None:
    cleaned = value.replace(",", "").replace(" ", "").strip()
    return int(cleaned) if _INT_RE.match(cleaned) else None


def _latest_snapshot() -> Path:
    if not RAW_ROOT.exists():
        raise SystemExit(f"no IRODaT bronze snapshots under {RAW_ROOT}")
    candidates = sorted(p for p in RAW_ROOT.iterdir() if p.is_dir())
    if not candidates:
        raise SystemExit(f"no dated subdirectories under {RAW_ROOT}")
    return candidates[-1]


def main() -> int:
    snapshot = _latest_snapshot()
    html_files = sorted(snapshot.glob("country_*.html"))
    if not html_files:
        print(f"ERROR: no country_*.html in {snapshot}", file=sys.stderr)
        return 1

    out_path = snapshot / "irodat_country_year.csv"
    written = 0

    with out_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(
            ["country_name", "report_year", "total_transplants", "deceased_donors", "living_donors"]
        )

        for html_path in html_files:
            extractor = _RowExtractor()
            try:
                extractor.feed(html_path.read_text(encoding="utf-8", errors="replace"))
            except Exception as exc:
                print(f"WARN: parse failed for {html_path.name}: {exc!r}", file=sys.stderr)
                continue

            country = extractor.title or html_path.stem
            for cells in extractor.rows:
                if len(cells) < 4:
                    continue
                year = _to_int(cells[0])
                if year is None:
                    continue
                total = _to_int(cells[1]) if len(cells) > 1 else None
                deceased = _to_int(cells[2]) if len(cells) > 2 else None
                living = _to_int(cells[3]) if len(cells) > 3 else None
                if total is None and deceased is None and living is None:
                    continue
                writer.writerow([country, year, total, deceased, living])
                written += 1

    print(f"wrote {written} rows → {out_path}")
    return 0 if written else 1


if __name__ == "__main__":
    sys.exit(main())
