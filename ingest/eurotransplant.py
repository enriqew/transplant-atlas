"""Bronze ingest: Eurotransplant Statistics Library HTML reports.

Downloads two public reports from statistics.eurotransplant.org that together
contain all data needed to populate the Eurotransplant series in
fct_transplants_world_country_year (2016-present, 7 ET member states):

  1. deceased_donors.html   — report 11034
     "Deceased donors used in Eurotransplant, by year, by donor country"
     Absolute counts, all ET countries, 2016-present.

  2. transplants_pmp.html   — report 10821-33157
     "Transplants per million population, by year, by country, by donor type"
     Rates (deceased + living + total pmp), 7 countries (Luxembourg excluded
     because its sample size is too small for meaningful pmp reporting).

The analysis script (analyses/eurotransplant_html_to_csv.py) combines both
reports with World Bank population data to produce et_national.csv.

Coverage: Austria (AUT), Belgium (BEL), Croatia (HRV), Germany (DEU),
          Hungary (HUN), Netherlands (NLD), Slovenia (SVN).
Luxembourg is covered by IRODaT (source_rank 4) instead.
"""

from __future__ import annotations

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

SOURCE = "eurotransplant"
_BASE_URL = "https://statistics.eurotransplant.org/reportloader.php"

# Report IDs from the ET Statistics Library.
# The version segment (-XXXXX) pins the report definition; update if ET
# restructures their library (which would also break the HTML parser).
_REPORTS = {
    "deceased_donors": f"{_BASE_URL}?report=11034&format=html&download=0",
    "transplants_pmp": f"{_BASE_URL}?report=10821-33157&format=html&download=0",
}


def main(argv: list[str] | None = None) -> int:
    args = build_argparser(SOURCE).parse_args(argv)
    log = configure_logging(SOURCE)

    if args.dry_run:
        for name, url in _REPORTS.items():
            log.info("--dry-run: would fetch %s -> %s.html", url, name)
        return 0

    try:
        target = ensure_snapshot_dir(SOURCE, args.snapshot_date, args.force)
    except SnapshotComplete as exc:
        log.info("snapshot already complete: %s — skipping", exc.path)
        return 0

    files: list[FileRecord] = []
    for report_name, url in _REPORTS.items():
        dest = target / f"{report_name}.html"
        log.info("fetching %s -> %s", url, dest.name)
        try:
            response = http_get(url, timeout=60)
        except Exception as exc:  # noqa: BLE001
            fail(f"failed to fetch {report_name}: {exc!r}", log=log)

        dest.write_bytes(response.content)
        files.append(
            FileRecord(
                name=dest.name,
                url=url,
                sha256=sha256_of(dest),
                bytes=dest.stat().st_size,
                row_count=None,
            )
        )
        log.info("wrote %s (%d bytes)", dest.name, dest.stat().st_size)

    write_meta(
        target,
        SnapshotMeta(
            source=SOURCE,
            snapshot_date=args.snapshot_date,
            fetched_at=utcnow_iso(),
            pipeline_version=pipeline_version(),
            files=files,
        ),
    )
    log.info("snapshot complete: %s", target)
    return 0


if __name__ == "__main__":
    sys.exit(main())
