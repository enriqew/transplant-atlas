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
    SnapshotComplete,
    SnapshotMeta,
    build_argparser,
    configure_logging,
    ensure_snapshot_dir,
    extended_ca_bundle,
    fail,
    pipeline_version,
    sha256_of,
    stream_to_file,
    utcnow_iso,
    write_meta,
)

# GODT (transplant-observatory.org) is served by ONT/Spain on a TLS cert issued by
# FNMT-RCM. The server doesn't include its intermediate "AC Componentes Informáticos"
# in the handshake, so we bundle that intermediate ourselves (downloaded once by the
# repo owner from the CA's published location; provenance + SHA256 are documented in
# ingest/certs/README.md) and merge it with certifi's defaults at request time.
FNMT_INTERMEDIATE_PEM = Path(__file__).resolve().parent / "certs" / "fnmt_accomp.pem"

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


MIN_TABLE_ROWS = 2     # one header + at least one data row
MIN_TABLE_COLS = 3     # < 3 columns is almost always a false-positive table detection
MIN_TABLE_BYTES = 100  # smaller than this and DuckDB's CSV sniffer chokes


def _extract_tables(pdf_path: Path, out_dir: Path, log) -> list[Path]:
    """Extract every page-level table to a separate CSV; returns the CSV paths in order.

    Filters out pdfplumber false positives (single-cell artifacts, mostly-empty rows)
    because DuckDB's CSV sniffer fails on near-empty files and pollutes the silver layer.
    """

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

                log.info("extracted table → %s (%d rows, %d cols)", csv_path.name, len(non_empty_rows), widest)
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

    try:
        target = ensure_snapshot_dir(SOURCE, args.snapshot_date, args.force)
    except SnapshotComplete as exc:
        log.info("snapshot already complete: %s — skipping", exc.path)
        return 0
    pdf_path = target / "global_report.pdf"

    if not FNMT_INTERMEDIATE_PEM.exists():
        fail(
            f"missing FNMT intermediate cert at {FNMT_INTERMEDIATE_PEM}; "
            "see ingest/certs/README.md for the provenance of this file",
            log=log,
        )
    ca_bundle = extended_ca_bundle([FNMT_INTERMEDIATE_PEM])
    log.info("using CA bundle with FNMT intermediate: %s", ca_bundle)

    log.info("downloading PDF → %s", pdf_path)
    try:
        pdf_bytes = stream_to_file(pdf_url, pdf_path, verify=str(ca_bundle))
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
