{{
  config(materialized='view')
}}

-- Bronze input: data/raw/godt_world/<snapshot_date>/page_*_table_*.csv
-- pdfplumber extracts every detectable table in the GODT global report PDF.
-- Most tables have country-level rows with these columns (after light header normalization):
--   Country
--   Year
--   Total transplants
--   Deceased donors
--   Living donors
--   Population (millions)
--
-- This model unions everything, filters out non-country header/footer rows, and joins
-- against the country_iso seed to produce a typed, ISO-coded fact table.

WITH raw AS (
    SELECT
        TRIM("Country")                       AS country_name_raw,
        TRY_CAST("Year" AS INTEGER)           AS report_year,
        TRY_CAST(REPLACE("Total transplants", ',', '') AS INTEGER)      AS total_transplants,
        TRY_CAST(REPLACE("Deceased donors", ',', '') AS INTEGER)        AS deceased_donors,
        TRY_CAST(REPLACE("Living donors", ',', '') AS INTEGER)          AS living_donors,
        filename                              AS source_filename
    FROM read_csv_auto(
        {{ latest_raw_csv_glob('godt_world') }},
        filename=true,
        ignore_errors=true,
        union_by_name=true
    )
    WHERE "Country" IS NOT NULL
)

SELECT
    country.country_iso3,
    country.country_name,
    raw.report_year,
    raw.total_transplants,
    raw.deceased_donors,
    raw.living_donors,
    'GODT'::VARCHAR AS source,
    {{ snapshot_date_from_filename('raw.source_filename') }}::DATE AS snapshot_date
FROM raw
INNER JOIN {{ ref('country_iso') }} AS country
    ON UPPER(country.country_name) = UPPER(raw.country_name_raw)
WHERE raw.report_year BETWEEN 1990 AND EXTRACT(YEAR FROM CURRENT_DATE)
  AND raw.total_transplants IS NOT NULL
