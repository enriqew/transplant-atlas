-- Singular test (severity: warn): for country-years covered by both
-- Eurotransplant and IRODaT, flag cases where the two sources diverge by
-- more than 25% in total_transplants.
--
-- A large divergence indicates one of:
--   - Counting methodology difference (ET counts organ allografts;
--     IRODaT may include or exclude certain organ types)
--   - An IRODaT reporting gap year (country submitted partial data)
--   - A genuine data loading error worth investigating
--
-- Severity is 'warn' because ET/IRODaT methodology differences are known
-- and documented. The test flags discrepancies for analyst review without
-- blocking the pipeline.
--
-- Threshold: 25% (ET pmp back-calculation introduces ~1-5% rounding;
--   >25% is almost certainly a real discrepancy, not rounding noise).

{{ config(severity='warn') }}

WITH et_rows AS (
    SELECT
        country_iso3,
        report_year                 AS year,
        total_transplants           AS et_total,
        deceased_donors             AS et_deceased
    FROM {{ ref('stg_eurotransplant') }}
),

irodat_rows AS (
    SELECT
        country_iso3,
        report_year                 AS year,
        total_transplants           AS irodat_total,
        deceased_donors             AS irodat_deceased
    FROM {{ ref('stg_irodat') }}
)

SELECT
    et.country_iso3,
    et.year,
    et.et_total,
    ir.irodat_total,
    et.et_deceased,
    ir.irodat_deceased,
    ROUND(ABS(et.et_total - ir.irodat_total) * 100.0 / ir.irodat_total, 1) AS pct_divergence_total
FROM et_rows AS et
INNER JOIN irodat_rows AS ir
    ON ir.country_iso3 = et.country_iso3
   AND ir.year = et.year
WHERE et.et_total >= 100
  AND ir.irodat_total >= 100
  AND ABS(et.et_total - ir.irodat_total) * 100.0 / ir.irodat_total > 25
ORDER BY et.country_iso3, et.year
