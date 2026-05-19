"""Build the four downstream artifacts from the gold DuckDB tables.

Outputs (data/exports/):
  - mexico-transplants.json
  - world-transplants.json
  - mexico-states.topojson
  - meta.json

Every JSON is validated against schemas/*.schema.json before write. Size limits
are asserted after write. Any failure causes a non-zero exit so CI never publishes
half-built artifacts.

Run:
    python -m export.build_artifacts --snapshot-date YYYY-MM-DD
"""

from __future__ import annotations

import argparse
import datetime as dt
import gzip
import json
import logging
import os
import sys
from collections import defaultdict
from pathlib import Path

import duckdb
import jsonschema
import topojson as tp

REPO_ROOT = Path(__file__).resolve().parent.parent
DUCKDB_PATH = Path(os.environ.get("TRANSPLANT_ATLAS_DUCKDB", REPO_ROOT / "data/duckdb/atlas.duckdb"))
EXPORTS_DIR = REPO_ROOT / "data/exports"
SCHEMAS_DIR = REPO_ROOT / "schemas"
RAW_BOUNDARIES_DIR = REPO_ROOT / "data/raw/mexico_boundaries"

JSON_MAX_GZIPPED_BYTES = 500_000
TOPOJSON_MAX_BYTES = 60_000
TOPOJSON_GZIPPED_MAX_BYTES = 30_000

# ISO 3166-2:MX state codes used to filter Natural Earth admin-1 polygons to Mexico only.
MX_STATE_CODES = {
    "AGU", "BCN", "BCS", "CAM", "CHP", "CHH", "CMX", "COA", "COL", "DUR",
    "GUA", "GRO", "HID", "JAL", "MEX", "MIC", "MOR", "NAY", "NLE", "OAX",
    "PUE", "QUE", "ROO", "SLP", "SIN", "SON", "TAB", "TAM", "TLA", "VER",
    "YUC", "ZAC",
}


def _configure_logging() -> logging.Logger:
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO"),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S%z",
        stream=sys.stderr,
    )
    return logging.getLogger("export.build_artifacts")


def _load_schema(name: str) -> dict:
    return json.loads((SCHEMAS_DIR / name).read_text(encoding="utf-8"))


def _validate(payload, schema_name: str, log: logging.Logger) -> None:
    """Validate against a JSON Schema draft 2020-12; raise on first error."""

    schema = _load_schema(schema_name)
    jsonschema.Draft202012Validator.check_schema(schema)
    validator = jsonschema.Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(payload), key=lambda e: e.path)
    if errors:
        for err in errors[:5]:
            log.error("schema violation in %s at %s: %s", schema_name, list(err.path), err.message)
        raise SystemExit(f"validation failed for {schema_name}")


def _write_json(path: Path, payload, log: logging.Logger) -> None:
    """Write JSON without spaces (compact) and verify gzipped size."""

    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    path.write_text(text + "\n", encoding="utf-8")

    gzipped = gzip.compress(text.encode("utf-8"))
    log.info("%s: %d bytes raw, %d gzipped", path.name, path.stat().st_size, len(gzipped))
    if len(gzipped) > JSON_MAX_GZIPPED_BYTES:
        raise SystemExit(
            f"{path.name} exceeds size limit: {len(gzipped)} > {JSON_MAX_GZIPPED_BYTES} gzipped"
        )


def _build_mexico_transplants(con: duckdb.DuckDBPyConnection) -> list[dict]:
    """One record per (state, year, organ). Joins fact transplants + donations + waitlist."""

    rows = con.execute(
        """
        WITH transplants AS (
            SELECT state_code, state_name, year, organ, transplants,
                   deceased_donor_transplants, living_donor_transplants, rate_pmp
            FROM fct_transplants_mx_state_year_organ
        ),
        donations AS (
            SELECT state_code, year, SUM(donations) AS donations
            FROM fct_donations_mx_state_year
            GROUP BY state_code, year
        ),
        waitlist AS (
            SELECT state_code, year, organ,
                   MAX(persons_waiting) FILTER (WHERE quarter = 4) AS waitlist_end_of_year
            FROM fct_waitlist_mx_state_quarter
            GROUP BY state_code, year, organ
        )
        SELECT
            transplants.state_code,
            transplants.state_name,
            transplants.year,
            transplants.organ,
            transplants.transplants,
            transplants.deceased_donor_transplants,
            transplants.living_donor_transplants,
            transplants.rate_pmp,
            donations.donations,
            waitlist.waitlist_end_of_year
        FROM transplants
        LEFT JOIN donations
            ON donations.state_code = transplants.state_code
           AND donations.year = transplants.year
        LEFT JOIN waitlist
            ON waitlist.state_code = transplants.state_code
           AND waitlist.year = transplants.year
           AND waitlist.organ = transplants.organ
        ORDER BY transplants.state_code, transplants.year, transplants.organ
        """
    ).fetchall()

    return [
        {
            "state_code": r[0],
            "state_name": r[1],
            "year": int(r[2]),
            "organ": r[3],
            "donations": (None if r[8] is None else int(r[8])),
            "transplants": (None if r[4] is None else int(r[4])),
            "waitlist_end_of_year": (None if r[9] is None else int(r[9])),
            "rate_pmp": (None if r[7] is None else float(r[7])),
            "donor_type_breakdown": {
                "deceased": (None if r[5] is None else int(r[5])),
                "living": (None if r[6] is None else int(r[6])),
            },
        }
        for r in rows
    ]


def _build_world_transplants(con: duckdb.DuckDBPyConnection) -> list[dict]:
    rows = con.execute(
        """
        SELECT
            country_iso3,
            country_name,
            year,
            total_transplants,
            deceased_donors,
            living_donors,
            deceased_donors_pmp,
            living_donors_pmp,
            transplants_pmp,
            source
        FROM fct_transplants_world_country_year
        ORDER BY country_iso3, year
        """
    ).fetchall()

    return [
        {
            "country_iso3": r[0],
            "country_name": r[1],
            "year": int(r[2]),
            "total_transplants": (None if r[3] is None else int(r[3])),
            "deceased_donors": (None if r[4] is None else int(r[4])),
            "living_donors": (None if r[5] is None else int(r[5])),
            "deceased_donors_pmp": (None if r[6] is None else float(r[6])),
            "living_donors_pmp": (None if r[7] is None else float(r[7])),
            "transplants_pmp": (None if r[8] is None else float(r[8])),
            "source": r[9],
        }
        for r in rows
    ]


def _build_mexico_topojson(log: logging.Logger) -> tuple[dict, Path]:
    """Read the cached Natural Earth admin-1 GeoJSON, filter to Mexico, return simplified TopoJSON."""

    if not RAW_BOUNDARIES_DIR.exists():
        raise SystemExit(
            f"missing {RAW_BOUNDARIES_DIR}; run `python -m ingest.mexico_boundaries` first"
        )
    snapshots = sorted(p for p in RAW_BOUNDARIES_DIR.iterdir() if p.is_dir())
    if not snapshots:
        raise SystemExit(f"no boundary snapshot under {RAW_BOUNDARIES_DIR}")
    snapshot = snapshots[-1]
    geojson_path = snapshot / "admin_1_states_provinces.geojson"
    if not geojson_path.exists():
        raise SystemExit(f"missing {geojson_path}")

    log.info("reading Mexican boundary polygons from %s", geojson_path)
    with geojson_path.open("rb") as fh:
        boundaries = json.load(fh)

    # Filter to Mexican states. Natural Earth fields: iso_3166_2 (eg "MX-JAL") and name.
    mexico_features = []
    for feature in boundaries.get("features", []):
        props = feature.get("properties", {})
        iso_full = (props.get("iso_3166_2") or "").upper()
        if not iso_full.startswith("MX-"):
            continue
        code = iso_full.split("-", 1)[1]
        if code not in MX_STATE_CODES:
            continue
        mexico_features.append(
            {
                "type": feature["type"],
                "geometry": feature["geometry"],
                "properties": {
                    "state_code": code,
                    "state_name": props.get("name") or code,
                },
            }
        )

    if len(mexico_features) != 32:
        log.warning(
            "expected 32 Mexican states, got %d — TopoJSON may be incomplete",
            len(mexico_features),
        )

    filtered = {"type": "FeatureCollection", "features": mexico_features}

    log.info("simplifying TopoJSON")
    topo = tp.Topology(filtered, prequantize=1e4, presimplify=True, toposimplify=0.05)
    topojson_obj = json.loads(topo.to_json())

    # Rename the object inside .objects to `states` for predictability downstream.
    if topojson_obj.get("objects"):
        first_key = next(iter(topojson_obj["objects"]))
        topojson_obj["objects"] = {"states": topojson_obj["objects"][first_key]}

    return topojson_obj, snapshot


def _collect_source_meta(log: logging.Logger) -> list[dict]:
    """Aggregate one entry per (source, snapshot_date) using each bronze meta.json."""

    out: list[dict] = []
    for source_dir in sorted((REPO_ROOT / "data/raw").iterdir() if (REPO_ROOT / "data/raw").exists() else []):
        if not source_dir.is_dir():
            continue
        for snapshot_dir in sorted(source_dir.iterdir()):
            meta_file = snapshot_dir / "meta.json"
            if not meta_file.exists():
                continue
            try:
                raw = json.loads(meta_file.read_text(encoding="utf-8"))
            except Exception as exc:  # noqa: BLE001
                log.warning("could not parse %s: %r", meta_file, exc)
                continue
            for f in raw.get("files", []):
                out.append(
                    {
                        "name": f"{raw['source']}::{f['name']}",
                        "url": f["url"],
                        "snapshot_date": raw["snapshot_date"],
                        "sha256": f["sha256"],
                        "rows_ingested": f.get("row_count"),
                        "bytes": f.get("bytes"),
                    }
                )
    return out


def _coverage(mexico: list[dict], world: list[dict]) -> dict:
    mx_years = sorted({rec["year"] for rec in mexico}) if mexico else []
    w_years = sorted({rec["year"] for rec in world}) if world else []
    countries = len({rec["country_iso3"] for rec in world})
    return {
        "mexico_years": [mx_years[0], mx_years[-1]] if mx_years else [0, 0],
        "world_years": [w_years[0], w_years[-1]] if w_years else [0, 0],
        "countries": countries,
    }


def _pipeline_version() -> str:
    pyproject = REPO_ROOT / "pyproject.toml"
    for raw in pyproject.read_text(encoding="utf-8").splitlines():
        cleaned = raw.strip()
        if cleaned.startswith("version"):
            return cleaned.split("=", 1)[1].strip().strip('"').strip("'")
    return "0.0.0+unknown"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="export.build_artifacts")
    parser.add_argument(
        "--snapshot-date",
        default=dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d"),
        help="Used only for stamping meta.json; bronze layer drives the actual data.",
    )
    args = parser.parse_args(argv)
    log = _configure_logging()

    if not DUCKDB_PATH.exists():
        raise SystemExit(
            f"DuckDB file not found at {DUCKDB_PATH}; run `make build` (dbt) first"
        )

    EXPORTS_DIR.mkdir(parents=True, exist_ok=True)

    log.info("connecting to %s", DUCKDB_PATH)
    con = duckdb.connect(str(DUCKDB_PATH), read_only=True)
    # dbt's schema config prefixes models with `main_gold`, `main_silver`, `main_seeds`;
    # set the search path so bare table names resolve in this read-only session.
    con.execute("SET search_path='main_gold,main_silver,main_seeds,main'")
    try:
        log.info("building mexico-transplants.json")
        mexico = _build_mexico_transplants(con)
        _validate(mexico, "mexico-transplants.schema.json", log)
        _write_json(EXPORTS_DIR / "mexico-transplants.json", mexico, log)

        log.info("building world-transplants.json")
        world = _build_world_transplants(con)
        _validate(world, "world-transplants.schema.json", log)
        _write_json(EXPORTS_DIR / "world-transplants.json", world, log)
    finally:
        con.close()

    log.info("building mexico-states.topojson")
    topojson_obj, boundary_snapshot = _build_mexico_topojson(log)
    topo_path = EXPORTS_DIR / "mexico-states.topojson"
    topo_text = json.dumps(topojson_obj, separators=(",", ":"))
    topo_path.write_text(topo_text + "\n", encoding="utf-8")
    topo_gz = len(gzip.compress(topo_text.encode("utf-8")))
    log.info("topojson: %d bytes raw, %d gzipped", topo_path.stat().st_size, topo_gz)
    if topo_path.stat().st_size > TOPOJSON_MAX_BYTES:
        raise SystemExit(
            f"mexico-states.topojson exceeds {TOPOJSON_MAX_BYTES} bytes raw "
            f"(got {topo_path.stat().st_size}); increase simplification."
        )
    if topo_gz > TOPOJSON_GZIPPED_MAX_BYTES:
        raise SystemExit(
            f"mexico-states.topojson exceeds {TOPOJSON_GZIPPED_MAX_BYTES} bytes gzipped "
            f"(got {topo_gz}); increase simplification."
        )

    log.info("building meta.json")
    meta_payload = {
        "generated_at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "pipeline_version": _pipeline_version(),
        "sources": _collect_source_meta(log),
        "artifact_row_counts": {
            "mexico_transplants": len(mexico),
            "world_transplants": len(world),
        },
        "coverage": _coverage(mexico, world),
    }
    _validate(meta_payload, "meta.schema.json", log)
    (EXPORTS_DIR / "meta.json").write_text(
        json.dumps(meta_payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    log.info("all artifacts written to %s", EXPORTS_DIR)
    log.info("  boundary snapshot used: %s", boundary_snapshot)
    return 0


if __name__ == "__main__":
    sys.exit(main())
