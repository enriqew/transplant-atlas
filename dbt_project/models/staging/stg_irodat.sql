{{
  config(materialized='view')
}}

-- Bronze input: data/raw/irodat/<snapshot_date>/country_*.html
-- IRODaT detail pages contain HTML tables, one per country, with year-by-year rows.
--
-- Parsing strategy: DuckDB's read_csv_auto cannot consume HTML directly. We invoke
-- a Python pre-step (see analyses/irodat_html_to_csv.py) that converts the HTML
-- snapshots to a single irodat_country_year.csv inside the same snapshot dir.
--
-- This staging model reads the pre-extracted CSV. If it is missing, the model fails
-- and signals that the pre-step has not run.

WITH raw AS (
    SELECT
        TRIM(country_name)                            AS country_name_raw,
        TRY_CAST(report_year AS INTEGER)              AS report_year,
        TRY_CAST(total_transplants AS INTEGER)        AS total_transplants,
        TRY_CAST(deceased_donors AS INTEGER)          AS deceased_donors,
        TRY_CAST(living_donors AS INTEGER)            AS living_donors,
        filename                                      AS source_filename
    FROM read_csv_auto(
        '{{ env_var("TRANSPLANT_ATLAS_RAW_ROOT", "../data/raw") }}/irodat/*/irodat_country_year.csv',
        filename=true,
        ignore_errors=false
    )
)

SELECT
    country.country_iso3,
    country.country_name,
    raw.report_year,
    raw.total_transplants,
    raw.deceased_donors,
    raw.living_donors,
    'IRODaT'::VARCHAR AS source,
    {{ snapshot_date_from_filename('raw.source_filename') }}::DATE AS snapshot_date
FROM raw
INNER JOIN {{ ref('country_iso') }} AS country
    ON UPPER(country.country_name) = UPPER(raw.country_name_raw)
WHERE raw.report_year BETWEEN 1990 AND EXTRACT(YEAR FROM CURRENT_DATE)
  AND raw.total_transplants IS NOT NULL
