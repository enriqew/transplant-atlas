"""Bronze ingest: Mexican state boundary polygons (for TopoJSON output).

Source: Natural Earth Admin-1 (states/provinces), 1:50m resolution, filtered to Mexico.
URL: https://naciscdn.org/naturalearth/50m/cultural/ne_50m_admin_1_states_provinces.zip
License: Natural Earth is public domain (https://www.naturalearthdata.com/about/terms-of-use/).

The export stage filters this to Mexican states only and simplifies to fit the ≤60KB
TopoJSON target.

Override the source URL at runtime via TRANSPLANT_ATLAS_BOUNDARY_URL if Natural Earth
moves or you want to swap to an INEGI direct download.
"""

from __future__ import annotations

import os
import sys

from ingest._common import (
    FileRecord,
    SnapshotMeta,
    build_argparser,
    configure_logging,
    ensure_snapshot_dir,
    fail,
    pipeline_version,
    sha256_of,
    stream_to_file,
    utcnow_iso,
    write_meta,
)

SOURCE = "mexico_boundaries"
DEFAULT_URL = (
    "https://naciscdn.org/naturalearth/50m/cultural/"
    "ne_50m_admin_1_states_provinces.zip"
)


def main(argv: list[str] | None = None) -> int:
    args = build_argparser(SOURCE).parse_args(argv)
    log = configure_logging(SOURCE)
    url = os.environ.get("TRANSPLANT_ATLAS_BOUNDARY_URL", DEFAULT_URL)
    log.info("source: %s", url)

    if args.dry_run:
        log.info("--dry-run: not downloading")
        return 0

    target = ensure_snapshot_dir(SOURCE, args.snapshot_date, args.force)
    dest = target / "admin_1_states_provinces.zip"
    log.info("downloading → %s", dest.name)

    try:
        n = stream_to_file(url, dest)
    except Exception as exc:  # noqa: BLE001
        fail(f"boundary download failed: {exc!r}", log=log)

    meta = SnapshotMeta(
        source=SOURCE,
        snapshot_date=args.snapshot_date,
        fetched_at=utcnow_iso(),
        pipeline_version=pipeline_version(),
        files=[
            FileRecord(
                name=dest.name,
                url=url,
                sha256=sha256_of(dest),
                bytes=n,
                row_count=None,
            )
        ],
    )
    write_meta(target, meta)
    log.info("snapshot complete: %s", target)
    return 0


if __name__ == "__main__":
    sys.exit(main())
