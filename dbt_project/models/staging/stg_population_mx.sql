{{
  config(materialized='view')
}}

-- Bronze input: data/raw/population_mx/<snapshot_date>/*.csv
-- Real CONAPO schema (verified 2026-05 against 00_Pob_Mitad_1950_2070.csv):
--   RENGLON, ANIO, ENTIDAD, CVE_GEO, EDAD, SEXO, POBLACION, ENTIDAD_FEDERATIVA, FECHA
-- Pure state-level (CVE_GEO 1..32), one row per (state, year, age, sex).
-- We aggregate to (state, year) totals for the pmp denominator.

WITH raw AS (
    SELECT
        TRY_CAST(CVE_GEO AS INTEGER)        AS cve_geo,
        TRY_CAST(ANIO AS INTEGER)           AS report_year,
        TRY_CAST(POBLACION AS BIGINT)       AS population,
        filename                            AS source_filename
    FROM read_csv_auto(
        {{ latest_raw_csv_glob('population_mx') }},
        filename=true,
        ignore_errors=false,
        union_by_name=true
    )
    WHERE ANIO IS NOT NULL
      AND POBLACION IS NOT NULL
)

SELECT
    states.state_code,
    states.state_name,
    raw.report_year,
    SUM(raw.population)                                AS population,
    {{ snapshot_date_from_filename('MAX(raw.source_filename)') }}::DATE AS snapshot_date
FROM raw
INNER JOIN {{ ref('mx_state_codes') }} AS states
    ON states.cve_geo = raw.cve_geo
GROUP BY
    states.state_code,
    states.state_name,
    raw.report_year
