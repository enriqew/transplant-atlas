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

# Captures every country code from the country-picker select on the index page.
# Options use the 2-letter IRODaT code as `value` (some prefixed with `_` for
# disambiguation), and the country name as the option text. Skip the placeholder
# whose value is "0".
COUNTRY_OPTION_RE = re.compile(
    r'<option\s+value="([^"]+)"[^>]*>\s*([^<]+?)\s*</option>',
    re.DOTALL | re.IGNORECASE,
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

    for code, name in countries:
        url = urljoin(BASE_URL, f"?p=database&c={code}#data")
        dest = target / f"country_{_safe_slug(code)}_{_safe_slug(name).lower()}.html"
        log.info("downloading %s (%s) → %s", code, name, dest.name)
        try:
            n = stream_to_file(url, dest)
        except Exception as exc:  # noqa: BLE001
            fail(f"IRODaT detail download failed for {url}: {exc!r}", log=log)
        meta.files.append(
            FileRecord(
                name=dest.name,
                url=url,
                sha256=sha256_of(dest),
                bytes=n,
                row_count=None,
            )
        )

    write_meta(target, meta)
    log.info("snapshot complete: %s (%d country pages)", target, len(countries))
    return 0


if __name__ == "__main__":
    sys.exit(main())
