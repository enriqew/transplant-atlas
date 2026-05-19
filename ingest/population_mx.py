"""Bronze ingest: Mexican state-level population (INEGI Census + CONAPO projections).

We pull CONAPO's state-by-year projections via datos.gob.mx (CKAN) when possible.
CONAPO publishes them under a dataset whose slug has historically been stable:
`proyecciones-de-la-poblacion-de-mexico` (or the year-suffixed variant).

If the dataset slug changes, override at runtime:
  TRANSPLANT_ATLAS_CONAPO_SLUG="<new-slug>" python -m ingest.population_mx ...

License: INEGI / CONAPO public statistics, attribution required.
"""

from __future__ import annotations

import os
import sys

from ingest._ckan import filter_csv, ingest_ckan_csv_dataset, list_dataset_resources
from ingest._common import build_argparser, configure_logging, fail

SOURCE = "population_mx"
DEFAULT_SLUG = "proyecciones-de-poblacion"


def main(argv: list[str] | None = None) -> int:
    args = build_argparser(SOURCE).parse_args(argv)
    log = configure_logging(SOURCE)
    slug = os.environ.get("TRANSPLANT_ATLAS_CONAPO_SLUG", DEFAULT_SLUG)

    log.info("using CONAPO dataset slug: %s", slug)

    # Sanity-probe first so we fail with a useful message if the slug rotated.
    try:
        resources = filter_csv(list_dataset_resources(slug))
    except Exception as exc:  # noqa: BLE001
        fail(
            f"CONAPO dataset discovery failed for slug={slug!r}: {exc!r}. "
            "Override via TRANSPLANT_ATLAS_CONAPO_SLUG env var if CONAPO has reissued it.",
            log=log,
        )

    if not resources:
        fail(
            f"CONAPO dataset {slug!r} has no CSV resources; check upstream.",
            log=log,
        )

    # CONAPO ships 11 CSVs under this slug (municipal, indicators, deaths, migration, ...).
    # We only want state-level mid-year population for the pmp denominator, so filter to
    # the "Población a mitad de año" file while excluding municipal breakdown.
    return ingest_ckan_csv_dataset(
        source=SOURCE,
        dataset_slug=slug,
        args=args,
        name_substrings=["mitad de año"],
        name_excludes=["municipio"],
    )


if __name__ == "__main__":
    sys.exit(main())
