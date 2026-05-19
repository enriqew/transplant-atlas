"""Bronze ingest: CENATRA transplants performed in Mexico.

Source: https://www.datos.gob.mx/dataset/trasplantes_organos_tejidos
Quarterly CSVs broken down by state, establishment, sex, age, blood type, and organ.
License: Libre Uso MX (open re-use with attribution).
"""

from __future__ import annotations

import sys

from ingest._ckan import ingest_ckan_csv_dataset
from ingest._common import build_argparser

SOURCE = "cenatra_transplants"
DATASET_SLUG = "trasplantes_organos_tejidos"


def main(argv: list[str] | None = None) -> int:
    args = build_argparser(SOURCE).parse_args(argv)
    return ingest_ckan_csv_dataset(source=SOURCE, dataset_slug=DATASET_SLUG, args=args)


if __name__ == "__main__":
    sys.exit(main())
