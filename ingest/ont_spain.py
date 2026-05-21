"""Bronze ingest: ONT España (Organización Nacional de Trasplantes) annual balance report.

ONT publishes one PDF per year at ont.es with Spain national donation and transplant
statistics. We download the PDF and extract every detectable table to CSV so the
pre-build analysis script (analyses/ont_spain_pdf_to_csv.py) can identify and
normalize the national series.

Source PDF URL: configurable via TRANSPLANT_ATLAS_ONT_PDF_URL; defaults to 2024 report.
Override when a newer annual balance is published each January.

TLS note: if the download fails with an SSLError, ont.es may use an FNMT-RCM
intermediate not included in the server handshake — see ingest/certs/README.md and
the extended_ca_bundle() pattern in godt_world.py for the same issuer.
"""

from __future__ import annotations

import csv
import os
import sys
from pathlib import Path

import pdfplumber

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

SOURCE = "ont_spain"
DEFAULT_PDF_URL = (
    "https://www.ont.es/wp-content/uploads/"
    "2025/01/BALANCE-ONT-2024-PRENSA-completo.pdf"
)

EXPECTED_PDFPLUMBER_VERSION = "0.11.4"

MIN_TABLE_ROWS = 2
MIN_TABLE_COLS = 3
MIN_TABLE_BYTES = 100


def _check_pdfplumber_version(log) -> None:
    actual = getattr(pdfplumber, "__version__", "unknown")
    if actual != EXPECTED_PDFPLUMBER_VERSION:
        fail(
            f"pdfplumber version drift: expected {EXPECTED_PDFPLUMBER_VERSION}, got {actual}. "
            "Re-validate ONT table extraction before bumping.",
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
                non_empty_rows = [
                    row for row in rows if row and any((cell or "").strip() for cell in row)
                ]
                if len(non_empty_rows) < MIN_TABLE_ROWS:
                    continue
                widest = max(len(row) for row in non_empty_rows)
                if widest < MIN_TABLE_COLS:
                    continue

                csv_path = out_dir / f"page_{page_index:03d}_table_{table_index}.csv"
                with csv_path.open("w", newline="", encoding="utf-8") as fh:
                    writer = csv.writer(fh)
                    for row in non_empty_rows:
                        writer.writerow([(cell or "").strip() for cell in row])

                if csv_path.stat().st_size < MIN_TABLE_BYTES:
                    csv_path.unlink()
                    continue

                log.info(
                    "extracted table → %s (%d rows, %d cols)",
                    csv_path.name,
                    len(non_empty_rows),
                    widest,
                )
                written.append(csv_path)
    return written


def main(argv: list[str] | None = None) -> int:
    args = build_argparser(SOURCE).parse_args(argv)
    log = configure_logging(SOURCE)
    _check_pdfplumber_version(log)

    pdf_url = os.environ.get("TRANSPLANT_ATLAS_ONT_PDF_URL", DEFAULT_PDF_URL)
    log.info("source PDF: %s", pdf_url)

    if args.dry_run:
        log.info("--dry-run: not downloading PDF")
        return 0

    try:
        target = ensure_snapshot_dir(SOURCE, args.snapshot_date, args.force)
    except SnapshotComplete as exc:
        log.info("snapshot already complete: %s — skipping", exc.path)
        return 0

    pdf_path = target / "ont_balance.pdf"

    log.info("downloading PDF → %s", pdf_path)
    try:
        pdf_bytes = stream_to_file(pdf_url, pdf_path)
    except Exception as exc:  # noqa: BLE001
        fail(f"PDF download failed: {exc!r}", log=log)

    log.info("extracting tables with pdfplumber")
    try:
        csv_paths = _extract_tables(pdf_path, target, log)
    except Exception as exc:  # noqa: BLE001
        fail(f"PDF table extraction failed (layout drift?): {exc!r}", log=log)

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
