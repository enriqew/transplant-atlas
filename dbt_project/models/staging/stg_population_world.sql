{{
  config(materialized='view')
}}

-- Bronze input: data/raw/population_world/<snapshot_date>/sp.pop.totl.json
-- World Bank JSON is a 2-element array: [metadata, rows]. We use DuckDB's JSON
-- extraction to unpack the rows array into a table.

WITH raw AS (
    SELECT
        UPPER(TRIM(row->>'$.countryiso3code'))      AS country_iso3_raw,
        TRY_CAST(row->>'$.date' AS INTEGER)         AS report_year,
        TRY_CAST(row->>'$.value' AS BIGINT)         AS population,
        TRIM(row->>'$.country.value')               AS country_name_raw,
        filename                                    AS source_filename
    FROM read_json_auto(
        '{{ env_var("TRANSPLANT_ATLAS_RAW_ROOT", "../data/raw") }}/population_world/*/sp.pop.totl.json',
        filename=true
    ) AS payload,
    UNNEST(payload.json[1]) AS t(row)
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
