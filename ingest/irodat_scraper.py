"""Bronze ingest: IRODaT international registry.

Source: https://www.irodat.org/?p=database
Public country-by-country registry of donation and transplantation indicators since 1996.

The page renders an HTML table per country/year. The exact request shape (GET with query
params vs POST with form data) has historically changed; we keep this script narrow:

  1. Fetch the main database page.
  2. Discover the per-country detail links from the rendered HTML.
  3. Persist the raw HTML for each detail page into the snapshot dir.
  4. Silver-layer SQL is responsible for parsing.

License: © IRODaT. Attribution required for any re-use.
"""

from __future__ import annotations

import re
import sys
from html.parser import HTMLParser
from urllib.parse import urljoin

from ingest._common import (
    FileRecord,
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


class _LinkCollector(HTMLParser):
    """Collect href targets that look like per-country IRODaT detail pages."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "a":
            return
        for key, value in attrs:
            if key.lower() == "href" and value:
                # IRODaT detail pages tend to look like ?p=database&c=<country code>
                if "p=database" in value and "c=" in value:
                    self.links.append(value)


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

    parser = _LinkCollector()
    parser.feed(index_html)
    detail_links = sorted(set(parser.links))
    log.info("discovered %d country detail links", len(detail_links))

    if not detail_links:
        fail(
            "no country detail links discovered on IRODaT index; site layout may have changed",
            log=log,
        )

    if args.dry_run:
        log.info("--dry-run: not writing snapshot")
        for link in detail_links[:5]:
            log.info("  example: %s", link)
        return 0

    target = ensure_snapshot_dir(SOURCE, args.snapshot_date, args.force)

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

    for href in detail_links:
        url = urljoin(BASE_URL, href)
        # Use the query string ("c=XX&...") as the file name slug
        suffix = href.split("?", 1)[-1]
        dest = target / f"country_{_safe_slug(suffix)}.html"
        log.info("downloading %s", url)
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
    log.info("snapshot complete: %s", target)
    return 0


if __name__ == "__main__":
    sys.exit(main())
