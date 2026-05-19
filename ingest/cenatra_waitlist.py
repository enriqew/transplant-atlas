"""Bronze ingest: CENATRA waiting list + establishments.

The waiting list dataset is published under the CENATRA organization rather than a single
package slug. We resolve it via CKAN's organization_show endpoint and pull every CSV in
the CENATRA org whose title looks like a waiting-list dataset.

Source: https://datos.gob.mx/busca/organization/80e28b47-8527-4926-87b9-7ccd26b5a2a0
License: Libre Uso MX.
"""

from __future__ import annotations

import sys

from ingest._ckan import (
    CkanResource,
    filter_csv,
    ingest_ckan_csv_dataset,
    list_dataset_resources,
)
from ingest._common import build_argparser, configure_logging, fail, http_get

SOURCE = "cenatra_waitlist"
ORG_ID = "80e28b47-8527-4926-87b9-7ccd26b5a2a0"
CKAN_BASE = "https://www.datos.gob.mx/api/3/action"


def _waitlist_datasets() -> list[str]:
    """Return dataset slugs in the CENATRA org whose title hints at waiting list."""

    response = http_get(f"{CKAN_BASE}/organization_show?id={ORG_ID}&include_datasets=true")
    payload = response.json()
    if not payload.get("success"):
        raise RuntimeError(f"CKAN organization_show failed: {payload}")
    keepers: list[str] = []
    for ds in payload["result"].get("packages", []):
        title = (ds.get("title") or "").lower()
        slug = ds.get("name")
        if not slug:
            continue
        if "espera" in title or "establec" in title:
            keepers.append(slug)
    return keepers


def main(argv: list[str] | None = None) -> int:
    args = build_argparser(SOURCE).parse_args(argv)
    log = configure_logging(SOURCE)

    try:
        slugs = _waitlist_datasets()
    except Exception as exc:  # noqa: BLE001
        fail(f"CKAN organization_show failed: {exc!r}", log=log)

    if not slugs:
        fail(
            "no waiting-list datasets found in CENATRA org; check upstream catalog",
            log=log,
        )

    log.info("waitlist-related dataset slugs: %s", slugs)

    if args.dry_run:
        # Probe resources without writing
        for slug in slugs:
            resources = filter_csv(list_dataset_resources(slug))
            log.info("  %s: %d CSV resources", slug, len(resources))
        return 0

    # Run the generic flow for each waitlist-related dataset; reuse the same snapshot dir.
    exit_codes = [
        ingest_ckan_csv_dataset(source=f"{SOURCE}__{slug}", dataset_slug=slug, args=args)
        for slug in slugs
    ]
    return max(exit_codes) if exit_codes else 0


if __name__ == "__main__":
    sys.exit(main())
