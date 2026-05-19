# transplant-atlas

> Offline data pipeline that ingests Mexican (CENATRA) and global (GODT / IRODaT) organ donation and transplantation statistics, normalizes them, computes per-million-population rates, and emits compact JSON / TopoJSON artifacts intended for static-site consumption.

The pipeline runs locally or on GitHub Actions free tier. It depends on no always-on infrastructure. The output artifacts (≤500 KB JSON, ≤60 KB TopoJSON) are committed to this repo and also published as workflow artifacts on every refresh.

A downstream agent (out of scope here) consumes those artifacts and renders an interactive map. See [the output contract](#output-contract).

## Status

Initial scaffolding complete. First end-to-end refresh pending — see commit history for current coverage. The authoritative spec is [`transplant-atlas-prompt.md`](./transplant-atlas-prompt.md); this README is the user-facing summary.

## Architecture

DuckDB + dbt-duckdb + Python. Medallion layout, fully offline:

```
Official URLs
    │
    ▼  ingest/  (Python)
BRONZE — data/raw/{source}/{YYYY-MM-DD}/  (immutable + SHA256 + meta.json)
    │
    ▼  dbt models/staging/
SILVER — DuckDB stg_*  (typed, ISO-normalized, English-only, tested)
    │
    ▼  dbt models/marts/
GOLD — DuckDB fct_* / dim_*  (pre-computed pmp rates)
    │
    ▼  export/build_artifacts.py
ARTIFACTS — data/exports/  (mexico-transplants.json, world-transplants.json,
                            mexico-states.topojson, meta.json)
```

- **DuckDB**: embedded SQL engine, single-file `.duckdb` (gitignored). Reads CSV/JSON via `read_csv_auto` / `read_json_auto`.
- **dbt-duckdb**: SQL-first transforms with `not_null` / `unique` / `accepted_values` / `relationships` tests on every model and seed.
- **Python**: ingest scripts only. Each one is `python -m ingest.<name>` runnable, accepts `--snapshot-date`, `--force`, `--dry-run`, and exits non-zero on any network or parsing failure.

### Sources

| Source | Layer | Notes |
|---|---|---|
| `cenatra_transplants` | Bronze CSV (CKAN) | https://www.datos.gob.mx/dataset/trasplantes_organos_tejidos |
| `cenatra_donations` | Bronze CSV (CKAN) | https://www.datos.gob.mx/dataset/donaciones_organos_tejidos_fines_trasplante |
| `cenatra_waitlist` | Bronze CSV (CKAN) | CENATRA organization → waiting-list packages |
| `population_mx` | Bronze CSV (CKAN) | CONAPO state-by-year-by-sex projections |
| `population_world` | Bronze JSON | World Bank `SP.POP.TOTL` |
| `godt_world` | Bronze PDF → CSVs | GODT global report; `pdfplumber==0.11.4` pinned |
| `irodat` | Bronze HTML → CSV | scrape of https://www.irodat.org/?p=database |
| `mexico_boundaries` | Bronze ZIP | Natural Earth admin-1, filtered to Mexico in export step |

The full Spanish-to-English organ mapping and ISO 3166-2:MX state codes live in `dbt_project/seeds/`.

## Reproduce locally

```bash
make install      # editable install + dev extras
make all          # ingest + dbt build + tests + export
ls data/exports/  # mexico-transplants.json, world-transplants.json, mexico-states.topojson, meta.json
```

Re-running with the same `SNAPSHOT_DATE` is idempotent. To force re-download:

```bash
make ingest SNAPSHOT_DATE=2026-05-18
# inside each ingest script you can also pass --force
```

To run a single ingest:

```bash
python -m ingest.cenatra_transplants --snapshot-date 2026-05-18 --dry-run
```

To debug SQL interactively:

```bash
duckdb data/duckdb/atlas.duckdb
> SELECT * FROM fct_transplants_mx_state_year_organ LIMIT 5;
```

## Output contract

Four artifacts under `data/exports/`. Schemas under `schemas/` (draft 2020-12) are authoritative — `export/build_artifacts.py` validates against them at write time.

- `mexico-transplants.json` — one record per `(state_code, year, organ)`; counts + `donor_type_breakdown` + `rate_pmp`.
- `world-transplants.json` — one record per `(country_iso3, year)`; counts + `*_pmp` rates + `source ∈ {GODT, IRODaT}`.
- `mexico-states.topojson` — INEGI/Natural Earth state polygons simplified to ≤60 KB.
- `meta.json` — provenance (per-source `url`, `snapshot_date`, `sha256`, `rows_ingested`), pipeline version, coverage ranges.

For field-level rules (when to use `null`, ISO patterns, organ enum), see the [schemas](./schemas/).

## Caveats

- **CENATRA reports by establishment, not patient residence.** A transplant performed in Mexico City for a patient who travelled from Oaxaca is counted under Mexico City. State-level rates therefore reflect *capacity*, not *need*.
- **GODT depends on voluntary country reporting.** Coverage of low-income countries is thin and inconsistent year over year. Missing country-years are emitted as absence, never as `0`.
- **CONAPO projections vs INEGI census.** Years between census years use CONAPO interpolation; the 2020 census reset the baseline.

## Privacy

This pipeline ingests **aggregate** statistics only — counts by establishment, state, or country for a given year. It does **not** ingest, store, or emit patient-level records or any personally identifiable information. The silver layer asserts this with `accepted_values` tests; if a future contribution attempts to bring in row-level patient data, those tests fail.

## Security notes (public repository)

- **No runtime secrets.** All upstream sources are unauthenticated open data. The pipeline must never require an API key.
- **Bronze raw data is gitignored** (`data/raw/**`), with the exception of per-snapshot `meta.json` sidecars so provenance is auditable without re-hosting upstream binaries.
- **GitHub Actions** uses `permissions: contents: write` only and `concurrency: refresh` to prevent parallel commits.
- Before any public push, run `git ls-files | xargs -I{} du -b {} | sort -rn | head` to confirm no surprisingly large file is tracked, and `grep -rE 'AKIA|api_key|password\s*='` to confirm no credential strings.

## Data source attributions and licenses

Source code is MIT (see [LICENSE](./LICENSE)). Upstream data retains its own terms:

| Source | License / terms |
|---|---|
| CENATRA via [datos.gob.mx](https://www.datos.gob.mx/) | "Libre Uso MX" — open re-use with attribution |
| World Bank `SP.POP.TOTL` | [CC BY 4.0](https://datacatalog.worldbank.org/public-licenses) |
| INEGI / CONAPO population projections | Public statistics, attribution required |
| GODT global report (PDF) | © GODT — fair-use snapshot only; do not redistribute the raw PDF |
| IRODaT registry | © IRODaT — attribution required; aggregated rows only |
| Natural Earth boundaries | Public domain (https://www.naturalearthdata.com/about/terms-of-use/) |

## License

Source code: [MIT](./LICENSE).
