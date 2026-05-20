"""Bronze ingest: IRODaT international registry.

Source: https://www.irodat.org/?p=database
Public country-by-country registry of donation and transplantation indicators since 1996.

The index page renders a `<select>` dropdown whose `<option>` values are 2-letter
IRODaT-specific country codes. Selecting a country navigates the browser to
`/?p=database&c=<code>#data`. We replicate that path-only: parse the select once,
then fetch each country detail page and persist the raw HTML.

Silver-layer parsing happens in a separate pre-step (dbt_project/analyses/irodat_html_to_csv.py).

License: © IRODaT. Attribution required for any re-use.
"""

from __future__ import annotations

import re
import sys
import time
from urllib.parse import urljoin

from ingest._common import (
    FileRecord,
    SnapshotComplete,
    SnapshotMeta,
    build_argparser,
    configure_logging,
    ensure_snapshot_dir,
    fail,
    http_get,
    pipeline_version,
    sha256_of,
    stream_to_file,
    utcnow_iso,
    write_meta,
)

SOURCE = "irodat"
BASE_URL = "https://www.irodat.org/"
INDEX_URL = "https://www.irodat.org/?p=database"

# Delay between successive country/year detail requests. IRODaT is a small
# public registry — be polite.
POLITE_DELAY_S = 0.4

# Captures every country code from the country-picker select on the index page.
# Options use the 2-letter IRODaT code as `value` (some prefixed with `_` for
# disambiguation), and the country name as the option text. Skip the placeholder
# whose value is "0".
COUNTRY_OPTION_RE = re.compile(
    r'<option\s+value="([^"]+)"[^>]*>\s*([^<]+?)\s*</option>',
    re.DOTALL | re.IGNORECASE,
)

# Captures historical year links from the per-country detail page.
# Markup: <div class="any"><a [class="actiu"] href="?p=database&c=XX&year=YYYY#data">YYYY</a></div>
YEAR_LINK_RE = re.compile(
    r'<a[^>]*href="\?p=database&c=([^&"]+)&year=(\d+)',
    re.IGNORECASE,
)


def _safe_slug(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9._-]+", "_", value).strip("_") or "page"


def main(argv: list[str] | None = None) -> int:
    args = build_argparser(SOURCE).parse_args(argv)
    log = configure_logging(SOURCE)

    log.info("fetching IRODaT index: %s", INDEX_URL)
    try:
        index_html = http_get(INDEX_URL).text
    except Exception as exc:  # noqa: BLE001
        fail(f"IRODaT index fetch failed: {exc!r}", log=log)

    countries: list[tuple[str, str]] = []
    for code, name in COUNTRY_OPTION_RE.findall(index_html):
        code = code.strip()
        name = re.sub(r"\s+", " ", name).strip()
        if code == "0" or not code or not name:
            continue
        countries.append((code, name))

    log.info("discovered %d country picker entries", len(countries))
    if not countries:
        fail(
            "no countries discovered in IRODaT index <select>; layout may have changed",
            log=log,
        )

    if args.dry_run:
        log.info("--dry-run: not writing snapshot")
        for code, name in countries[:5]:
            log.info("  example: %s = %s", code, name)
        return 0

    try:
        target = ensure_snapshot_dir(SOURCE, args.snapshot_date, args.force)
    except SnapshotComplete as exc:
        log.info("snapshot already complete: %s — skipping", exc.path)
        return 0

    index_path = target / "_index.html"
    index_path.write_text(index_html, encoding="utf-8")

    meta = SnapshotMeta(
        source=SOURCE,
        snapshot_date=args.snapshot_date,
        fetched_at=utcnow_iso(),
        pipeline_version=pipeline_version(),
        files=[
            FileRecord(
                name=index_path.name,
                url=INDEX_URL,
                sha256=sha256_of(index_path),
                bytes=index_path.stat().st_size,
                row_count=None,
            )
        ],
    )

    total_pages = 0
    for code, name in countries:
        slug = _safe_slug(code)
        name_slug = _safe_slug(name).lower()

        # Step 1: fetch the country default page (latest year + list of all
        # historical years). Keep the legacy filename — silver parser globs
        # `country_*.html` and extracts the year from the table contents.
        default_url = urljoin(BASE_URL, f"?p=database&c={code}#data")
        default_dest = target / f"country_{slug}_{name_slug}.html"
        if default_dest.exists() and default_dest.stat().st_size > 0:
            log.info("default page exists for %s — reusing %s", code, default_dest.name)
        else:
            log.info("downloading %s (%s) default → %s", code, name, default_dest.name)
            try:
                stream_to_file(default_url, default_dest)
            except Exception as exc:  # noqa: BLE001
                fail(f"IRODaT default download failed for {default_url}: {exc!r}", log=log)
            time.sleep(POLITE_DELAY_S)
        default_html = default_dest.read_text(encoding="utf-8", errors="replace")
        meta.files.append(
            FileRecord(
                name=default_dest.name,
                url=default_url,
                sha256=sha256_of(default_dest),
                bytes=default_dest.stat().st_size,
                row_count=None,
            )
        )
        total_pages += 1

        # Step 2: parse the historical-year picker. Each link looks like
        # `?p=database&c=XX&year=YYYY` — keep only the ones for this country.
        years_found: set[int] = set()
        for matched_code, year_str in YEAR_LINK_RE.findall(default_html):
            if matched_code == code:
                try:
                    years_found.add(int(year_str))
                except ValueError:
                    continue
        log.info("  → %d historical year link(s) advertised for %s", len(years_found), code)

        # Step 3: fetch each non-default year individually. Skip files that
        # already exist on disk for fine-grained resumability.
        for year in sorted(years_found):
            year_url = urljoin(BASE_URL, f"?p=database&c={code}&year={year}#data")
            year_dest = target / f"country_{slug}_{name_slug}_y{year}.html"
            if year_dest.exists() and year_dest.stat().st_size > 0:
                log.info("    year %d exists — reusing %s", year, year_dest.name)
            else:
                log.info("    year %d → %s", year, year_dest.name)
                try:
                    stream_to_file(year_url, year_dest)
                except Exception as exc:  # noqa: BLE001
                    log.warning("    skipping %s year %d: %r", code, year, exc)
                    continue
                time.sleep(POLITE_DELAY_S)
            meta.files.append(
                FileRecord(
                    name=year_dest.name,
                    url=year_url,
                    sha256=sha256_of(year_dest),
                    bytes=year_dest.stat().st_size,
                    row_count=None,
                )
            )
            total_pages += 1

    write_meta(target, meta)
    log.info(
        "snapshot complete: %s (%d countries, %d total HTML pages)",
        target,
        len(countries),
        total_pages,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
