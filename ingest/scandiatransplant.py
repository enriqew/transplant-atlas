"""Bronze ingest: Scandiatransplant annual XLSX report.

Downloads the public XLSX published annually at scandiatransplant.org.
The file is named with a date suffix (e.g., Scandiatransplant_tx_figures_01jan2026.xlsx)
and is fetched via the fixed /data/scandiatransplant-figures/ path.

Coverage: Denmark (DNK), Sweden (SWE), Norway (NOR), Finland (FIN),
          Iceland (ISL), Estonia (EST) — 1979 to present.

The analysis script (analyses/scandiatransplant_xlsx_to_csv.py) parses the XLSX
and produces sctp_national.csv used by stg_scandiatransplant.
"""

from __future__ import annotations

import re
import sys

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
    utcnow_iso,
    write_meta,
)

SOURCE = "scandiatransplant"

# The XLSX filename contains a date suffix that updates each publication.
# We discover the current filename via the index page rather than hardcoding it.
_INDEX_URL = "https://www.scandiatransplant.org/data/scandiatransplant-figures"
_FILENAME_PATTERN = re.compile(
    r'href="([^"]*Scandiatransplant_tx_figures_[^"]+\.xlsx)"',
    re.IGNORECASE,
)


def _resolve_xlsx_url(log) -> str:
    """Scrape the index page to find the current XLSX download URL."""
    response = http_get(_INDEX_URL, timeout=60)
    html = response.text

    matches = _FILENAME_PATTERN.findall(html)
    if not matches:
        fail("could not find XLSX link on Scandiatransplant figures page", log=log)

    href = matches[0]
    if href.startswith("http"):
        return href
    # Relative URL — build absolute
    base = "https://www.scandiatransplant.org"
    return base + ("" if href.startswith("/") else "/") + href


def main(argv: list[str] | None = None) -> int:
    args = build_argparser(SOURCE).parse_args(argv)
    log = configure_logging(SOURCE)

    if args.dry_run:
        log.info("--dry-run: would scrape %s and fetch XLSX", _INDEX_URL)
        return 0

    try:
        target = ensure_snapshot_dir(SOURCE, args.snapshot_date, args.force)
    except SnapshotComplete as exc:
        log.info("snapshot already complete: %s — skipping", exc.path)
        return 0

    log.info("resolving current XLSX URL from %s", _INDEX_URL)
    try:
        url = _resolve_xlsx_url(log)
    except Exception as exc:  # noqa: BLE001
        fail(f"failed to resolve XLSX URL: {exc!r}", log=log)

    filename = url.split("/")[-1].split("?")[0] or "scandiatransplant.xlsx"
    dest = target / filename
    log.info("fetching %s -> %s", url, dest.name)
    try:
        response = http_get(url, timeout=120)
    except Exception as exc:  # noqa: BLE001
        fail(f"failed to fetch XLSX: {exc!r}", log=log)

    dest.write_bytes(response.content)
    log.info("wrote %s (%d bytes)", dest.name, dest.stat().st_size)

    write_meta(
        target,
        SnapshotMeta(
            source=SOURCE,
            snapshot_date=args.snapshot_date,
            fetched_at=utcnow_iso(),
            pipeline_version=pipeline_version(),
            files=[
                FileRecord(
                    name=dest.name,
                    url=url,
                    sha256=sha256_of(dest),
                    bytes=dest.stat().st_size,
                    row_count=None,
                )
            ],
        ),
    )
    log.info("snapshot complete: %s", target)
    return 0


if __name__ == "__main__":
    sys.exit(main())
