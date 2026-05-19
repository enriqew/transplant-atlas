{{
  config(materialized='view')
}}

-- Bronze input: data/raw/population_world/<snapshot_date>/sp.pop.totl.rows.ndjson
-- The NDJSON file is produced by the analyses/wb_json_to_ndjson.py prebuild step,
-- which unwraps the World Bank `[meta, rows]` envelope into one record per line.

WITH raw AS (
    SELECT
        UPPER(TRIM(countryiso3code))                AS country_iso3_raw,
        TRY_CAST(date AS INTEGER)                   AS report_year,
        TRY_CAST(value AS BIGINT)                   AS population,
        filename                                    AS source_filename
    FROM read_json(
        '{{ env_var("TRANSPLANT_ATLAS_RAW_ROOT", "../data/raw") }}/population_world/*/sp.pop.totl.rows.ndjson',
        format='newline_delimited',
        filename=true
    )
    WHERE value IS NOT NULL
      AND countryiso3code IS NOT NULL
)

SELECT
    country.country_iso3,
    country.country_name,
    raw.report_year,
    raw.population,
    {{ snapshot_date_from_filename('raw.source_filename') }}::DATE AS snapshot_date
FROM raw
INNER JOIN {{ ref('country_iso') }} AS country
    ON country.country_iso3 = raw.country_iso3_raw
WHERE raw.population IS NOT NULL
  AND raw.report_year BETWEEN 1990 AND EXTRACT(YEAR FROM CURRENT_DATE)
