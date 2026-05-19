"""Pre-step for stg_irodat: convert IRODaT per-country HTML snapshots to a single CSV.

Reads all `country_*.html` files inside the latest data/raw/irodat/<date>/ snapshot
and emits `irodat_country_year.csv` with columns:
  country_name, report_year, total_transplants, deceased_donors, living_donors

Each IRODaT country page renders a fixed set of summary tables for the latest year.
We target two of them by heading text:
  - "ORGAN DONATIONS" (detailed): contains Actual Deceased Donors NUM + Living Donors NUM
  - "ORGAN TRANSPLANTS"          : contains kidney/liver/pancreas/heart/lung counts
                                   broken down by DECEASED and LIVING rows

Total transplants = sum of all organ NUM columns across both DECEASED and LIVING rows.

Failure modes:
  - No HTML files found in the latest snapshot → exit non-zero
  - A specific HTML cannot be parsed → log warning, skip that country; never fabricate.
"""

from __future__ import annotations

import csv
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
RAW_ROOT = REPO_ROOT / "data" / "raw" / "irodat"

TITLE_SUFFIXES = [
    " deceased organ donor evolution",
    " living organ donor evolution",
    " organ donor evolution",
    " transplant activity",
]

# Table regex: captures every <table>...</table> block (DOTALL so newlines match)
TABLE_RE = re.compile(r"<table[^>]*>(.*?)</table>", re.DOTALL | re.IGNORECASE)
TR_RE = re.compile(r"<tr[^>]*>(.*?)</tr>", re.DOTALL | re.IGNORECASE)
CELL_RE = re.compile(r"<t[hd][^>]*>(.*?)</t[hd]>", re.DOTALL | re.IGNORECASE)
TAG_RE = re.compile(r"<[^>]+>")
WHITESPACE_RE = re.compile(r"\s+")
H1_RE = re.compile(r"<h1[^>]*>(.*?)</h1>", re.DOTALL | re.IGNORECASE)
H1_COUNTRY_RE = re.compile(
    r'<h1[^>]*class="[^"]*\bcountry\b[^"]*"[^>]*>(.*?)</h1>',
    re.DOTALL | re.IGNORECASE,
)


def _clean(html_fragment: str) -> str:
    return WHITESPACE_RE.sub(" ", TAG_RE.sub("", html_fragment)).strip()


def _to_int(value: str) -> int | None:
    """Lenient int parse: handles thousands separators and rejects '-' / empty."""

    cleaned = value.replace(",", "").replace(" ", "").strip()
    if not cleaned or cleaned in {"-", "—"}:
        return None
    try:
        return int(cleaned)
    except ValueError:
        return None


def _extract_rows(table_html: str) -> list[list[str]]:
    rows = []
    for tr in TR_RE.findall(table_html):
        cells = [_clean(c) for c in CELL_RE.findall(tr)]
        if cells:
            rows.append(cells)
    return rows


def _country_name(html: str, fallback: str) -> str:
    """Prefer the per-country <h1 class="country">…</h1>; fall back to suffix-stripping H1 or filename."""

    match = H1_COUNTRY_RE.search(html)
    if match:
        raw = _clean(match.group(1))
        if raw:
            return raw

    for h1 in H1_RE.findall(html):
        raw = _clean(h1)
        lower = raw.lower()
        for suffix in TITLE_SUFFIXES:
            if lower.endswith(suffix):
                return raw[: -len(suffix)].strip()
        if raw and raw.upper() not in {"DATABASE", "IRODAT"}:
            return raw

    return fallback


def _parse_year(rows: list[list[str]]) -> int | None:
    """First row's second cell on the headline tables is the year."""

    if not rows:
        return None
    header = rows[0]
    if len(header) >= 2:
        year = _to_int(header[1])
        if year and 1990 <= year <= 2100:
            return year
    return None


def _parse_donations(table_html: str) -> tuple[int | None, int | None, int | None]:
    """Return (year, deceased_donors, living_donors) from the detailed ORGAN DONATIONS
    table, identified by the presence of 'Actual Deceased Donors' in its header.

    Layout (Spain example):
        row 0: ['ORGAN DONATIONS', '2024', 'Actual Deceased Donors', 'Utilized Deceased Donors',
                'Actual DCD Donors', 'Utilized DCD Donors', 'Living Donors', '']
        row 1: NUM/PMP repeated 5 times (so 10 cells)
        row 2: data: ['', '', '2562', '53.93', '2278', '47.95', '1316', '27.71', '1149', '24.19', '405', '8.53']
    Index mapping (data row): index 2 = Actual Deceased NUM; index 10 = Living NUM.
    """

    rows = _extract_rows(table_html)
    if len(rows) < 3:
        return None, None, None
    header = rows[0]
    if not any("Actual Deceased Donors".lower() in _clean(h).lower() for h in header):
        return None, None, None

    year = _parse_year(rows)
    data = rows[2]
    deceased = _to_int(data[2]) if len(data) > 2 else None
    living = _to_int(data[10]) if len(data) > 10 else None
    return year, deceased, living


def _parse_transplants(table_html: str) -> tuple[int | None, int | None]:
    """Return (year, total_transplants) from the ORGAN TRANSPLANTS table.

    Layout (Mexico example):
        row 0: ['ORGAN TRANSPLANTS', '2024', 'KIDNEY', 'LIVER', 'PANCREAS', 'HEART', 'LUNG', 'HEART LUNG', '']
        row 1: NUM/PMP repeated 6 times (12 cells)
        row 2: ['', 'DECEASED', '990', '7.65', '267', '2.06', '0', '0', '43', '0.33', '16', '0.12', '-', '-']
        row 3: ['', 'LIVING',   '1751', ...]
    Total = sum of NUM columns at indices 2, 4, 6, 8, 10, 12 of rows 2 & 3.
    """

    rows = _extract_rows(table_html)
    if len(rows) < 3:
        return None, None
    header = rows[0]
    header_text = " ".join(_clean(h).lower() for h in header)
    if "organ transplants" not in header_text:
        return None, None

    year = _parse_year(rows)
    total = 0
    found_any = False
    for data_row in rows[2:]:
        # NUM columns are at even indices starting at 2 (after the empty + label cells).
        for idx in range(2, len(data_row), 2):
            value = _to_int(data_row[idx])
            if value is not None:
                total += value
                found_any = True
    return year, total if found_any else None


def _latest_snapshot() -> Path:
    if not RAW_ROOT.exists():
        raise SystemExit(f"no IRODaT bronze snapshots under {RAW_ROOT}")
    candidates = sorted(p for p in RAW_ROOT.iterdir() if p.is_dir())
    if not candidates:
        raise SystemExit(f"no dated subdirectories under {RAW_ROOT}")
    return candidates[-1]


def _extract_one(html: str, fallback_name: str) -> dict | None:
    """Parse a single country HTML page; return one summary dict or None."""

    tables = TABLE_RE.findall(html)
    if not tables:
        return None

    year, deceased, living = (None, None, None)
    transplants = None
    for table_html in tables:
        if year is None or deceased is None or living is None:
            year_d, dec, liv = _parse_donations(table_html)
            year = year or year_d
            deceased = deceased if deceased is not None else dec
            living = living if living is not None else liv
        if transplants is None:
            year_t, tot = _parse_transplants(table_html)
            year = year or year_t
            transplants = tot

    if year is None:
        return None
    if transplants is None and deceased is None and living is None:
        return None

    return {
        "country_name": _country_name(html, fallback_name),
        "report_year": year,
        "total_transplants": transplants,
        "deceased_donors": deceased,
        "living_donors": living,
    }


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
            try:
                html = html_path.read_text(encoding="utf-8", errors="replace")
            except Exception as exc:  # noqa: BLE001
                print(f"WARN: read failed for {html_path.name}: {exc!r}", file=sys.stderr)
                continue
            record = _extract_one(html, fallback_name=html_path.stem)
            if record is None:
                continue
            writer.writerow(
                [
                    record["country_name"],
                    record["report_year"],
                    record["total_transplants"],
                    record["deceased_donors"],
                    record["living_donors"],
                ]
            )
            written += 1

    print(f"wrote {written} rows → {out_path}")
    return 0 if written else 1


if __name__ == "__main__":
    sys.exit(main())
