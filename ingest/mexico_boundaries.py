"""Bronze ingest: Mexican state boundary polygons (for TopoJSON output).

Source: Natural Earth Admin-1 (states/provinces), 1:50m resolution, GeoJSON form
mirrored at github.com/nvkelso/natural-earth-vector. We use the GeoJSON variant
(not the canonical shapefile zip) so the export stage doesn't need a shapefile
reader. The export step filters to Mexican states and simplifies to ≤60 KB TopoJSON.

License: Natural Earth is public domain
  (https://www.naturalearthdata.com/about/terms-of-use/).

Override via TRANSPLANT_ATLAS_BOUNDARY_URL if you prefer an INEGI direct download
(remember to update the export-side feature filter to match its property names).
"""

from __future__ import annotations

import os
import sys

from ingest._common import (
    FileRecord,
    SnapshotComplete,
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
    "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/"
    "master/geojson/ne_50m_admin_1_states_provinces.geojson"
)


def main(argv: list[str] | None = None) -> int:
    args = build_argparser(SOURCE).parse_args(argv)
    log = configure_logging(SOURCE)
    url = os.environ.get("TRANSPLANT_ATLAS_BOUNDARY_URL", DEFAULT_URL)
    log.info("source: %s", url)

    if args.dry_run:
        log.info("--dry-run: not downloading")
        return 0

    try:
        target = ensure_snapshot_dir(SOURCE, args.snapshot_date, args.force)
    except SnapshotComplete as exc:
        log.info("snapshot already complete: %s — skipping", exc.path)
        return 0
    dest = target / "admin_1_states_provinces.geojson"
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
