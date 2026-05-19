"""Bronze ingest: World Bank total population (`SP.POP.TOTL`).

API: https://api.worldbank.org/v2/country/all/indicator/SP.POP.TOTL?format=json&per_page=20000
License: CC BY 4.0 (https://datacatalog.worldbank.org/public-licenses).

The endpoint returns paginated JSON. We request a generous page size and verify the
returned page count matches what World Bank advertises in the response metadata.
"""

from __future__ import annotations

import json
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

SOURCE = "population_world"
INDICATOR = "SP.POP.TOTL"
URL = (
    "https://api.worldbank.org/v2/country/all/indicator/"
    f"{INDICATOR}?format=json&per_page=20000"
)


def main(argv: list[str] | None = None) -> int:
    args = build_argparser(SOURCE).parse_args(argv)
    log = configure_logging(SOURCE)

    log.info("fetching World Bank indicator %s", INDICATOR)
    try:
        response = http_get(URL)
        payload = response.json()
    except Exception as exc:  # noqa: BLE001
        fail(f"World Bank request failed: {exc!r}", log=log)

    if not isinstance(payload, list) or len(payload) != 2:
        fail(f"unexpected World Bank response shape: {type(payload).__name__}", log=log)

    meta_block, rows = payload
    pages = meta_block.get("pages", 1)
    if pages > 1:
        fail(
            f"World Bank returned {pages} pages; raise per_page or paginate. Not implemented.",
            log=log,
        )

    if not rows:
        fail("World Bank returned zero rows", log=log)

    log.info("received %d rows", len(rows))

    if args.dry_run:
        log.info("--dry-run: not writing snapshot")
        return 0

    try:
        target = ensure_snapshot_dir(SOURCE, args.snapshot_date, args.force)
    except SnapshotComplete as exc:
        log.info("snapshot already complete: %s — skipping", exc.path)
        return 0
    dest = target / f"{INDICATOR.lower()}.json"
    dest.write_text(json.dumps(payload, ensure_ascii=False) + "\n", encoding="utf-8")

    meta = SnapshotMeta(
        source=SOURCE,
        snapshot_date=args.snapshot_date,
        fetched_at=utcnow_iso(),
        pipeline_version=pipeline_version(),
        files=[
            FileRecord(
                name=dest.name,
                url=URL,
                sha256=sha256_of(dest),
                bytes=dest.stat().st_size,
                row_count=len(rows),
            )
        ],
    )
    write_meta(target, meta)
    log.info("snapshot complete: %s", target)
    return 0


if __name__ == "__main__":
    sys.exit(main())
