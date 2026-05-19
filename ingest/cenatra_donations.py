"""Bronze ingest: CENATRA donations (organ and tissue donations for transplant purposes).

Source: https://www.datos.gob.mx/dataset/donaciones_organos_tejidos_fines_trasplante
License: Libre Uso MX.
"""

from __future__ import annotations

import sys

from ingest._ckan import ingest_ckan_csv_dataset
from ingest._common import build_argparser

SOURCE = "cenatra_donations"
DATASET_SLUG = "donaciones_organos_tejidos_fines_trasplante"


def main(argv: list[str] | None = None) -> int:
    args = build_argparser(SOURCE).parse_args(argv)
    return ingest_ckan_csv_dataset(source=SOURCE, dataset_slug=DATASET_SLUG, args=args)


if __name__ == "__main__":
    sys.exit(main())
