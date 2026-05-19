"""Bronze ingest: GODT (Global Observatory on Donation and Transplantation) annual report.

GODT (WHO + Spanish ONT) publishes a single annual PDF with country tables for
donation and transplantation. We download the PDF, extract every detectable table
to CSV, and record the source layout so silver-layer parsing can be deterministic.

Source PDF URL: configurable; defaults to the 2024-data global report.
Override via TRANSPLANT_ATLAS_GODT_PDF_URL if a newer report is published.

License: © GODT. Fair-use snapshot only. Do not redistribute the raw PDF.
"""

from __future__ import annotations

import csv
import os
import sys
from pathlib import Path

import pdfplumber

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

SOURCE = "godt_world"
DEFAULT_PDF_URL = (
    "https://www.transplant-observatory.org/wp-content/uploads/"
    "2025/12/2024-data-global-report.pdf"
)

# Pinned pdfplumber version asserted in pyproject.toml. If it drifts, fail loudly so a
# committer can re-validate that the table-extraction output still matches the schema.
EXPECTED_PDFPLUMBER_VERSION = "0.11.4"


def _check_pdfplumber_version(log) -> None:
    actual = getattr(pdfplumber, "__version__", "unknown")
    if actual != EXPECTED_PDFPLUMBER_VERSION:
        fail(
            f"pdfplumber version drift: expected {EXPECTED_PDFPLUMBER_VERSION}, got {actual}. "
            "Re-validate GODT table extraction before bumping.",
            log=log,
        )


def _extract_tables(pdf_path: Path, out_dir: Path, log) -> list[Path]:
    """Extract every page-level table to a separate CSV; returns the CSV paths in order."""

    written: list[Path] = []
    with pdfplumber.open(pdf_path) as pdf:
        for page_index, page in enumerate(pdf.pages, start=1):
            tables = page.extract_tables()
            if not tables:
                continue
            for table_index, rows in enumerate(tables, start=1):
                if not rows or all(not any(cell or "" for cell in row) for row in rows):
                    continue
                csv_path = out_dir / f"page_{page_index:03d}_table_{table_index}.csv"
                with csv_path.open("w", newline="", encoding="utf-8") as fh:
                    writer = csv.writer(fh)
                    for row in rows:
                        writer.writerow([(cell or "").strip() for cell in row])
                log.info("extracted table → %s (%d rows)", csv_path.name, len(rows))
                written.append(csv_path)
    return written


def main(argv: list[str] | None = None) -> int:
    args = build_argparser(SOURCE).parse_args(argv)
    log = configure_logging(SOURCE)
    _check_pdfplumber_version(log)

    pdf_url = os.environ.get("TRANSPLANT_ATLAS_GODT_PDF_URL", DEFAULT_PDF_URL)
    log.info("source PDF: %s", pdf_url)

    if args.dry_run:
        log.info("--dry-run: not downloading PDF")
        return 0

    target = ensure_snapshot_dir(SOURCE, args.snapshot_date, args.force)
    pdf_path = target / "global_report.pdf"

    log.info("downloading PDF → %s", pdf_path)
    try:
        pdf_bytes = stream_to_file(pdf_url, pdf_path)
    except Exception as exc:  # noqa: BLE001
        fail(f"PDF download failed: {exc!r}", log=log)

    log.info("extracting tables with pdfplumber")
    try:
        csv_paths = _extract_tables(pdf_path, target, log)
    except Exception as exc:  # noqa: BLE001
        fail(
            f"PDF table extraction failed (layout drift?): {exc!r}",
            log=log,
        )

    if not csv_paths:
        fail("PDF contained no extractable tables", log=log)

    meta = SnapshotMeta(
        source=SOURCE,
        snapshot_date=args.snapshot_date,
        fetched_at=utcnow_iso(),
        pipeline_version=pipeline_version(),
        files=[
            FileRecord(
                name=pdf_path.name,
                url=pdf_url,
                sha256=sha256_of(pdf_path),
                bytes=pdf_bytes,
                row_count=None,
            )
        ],
    )
    for csv_path in csv_paths:
        with csv_path.open("rb") as fh:
            n_rows = sum(1 for _ in fh)
        meta.files.append(
            FileRecord(
                name=csv_path.name,
                url=pdf_url,
                sha256=sha256_of(csv_path),
                bytes=csv_path.stat().st_size,
                row_count=max(n_rows - 1, 0),
            )
        )

    write_meta(target, meta)
    log.info("snapshot complete: %s", target)
    return 0


if __name__ == "__main__":
    sys.exit(main())
