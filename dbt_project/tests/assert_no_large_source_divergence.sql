-- Singular test (severity: warn): for country-years covered by both a
-- regional registry (Eurotransplant or Scandiatransplant) and IRODaT,
-- flag cases where the two sources diverge by more than 25% in
-- total_transplants.
--
-- A large divergence indicates one of:
--   - Counting methodology difference (regional registries count organ
--     allografts; IRODaT may include or exclude certain organ types)
--   - An IRODaT reporting gap year (country submitted partial data)
--   - A genuine data loading error worth investigating
--
-- Severity is 'warn' because methodology differences are known and
-- documented. Regional registries supersede IRODaT in the mart, so
-- divergences don't affect output — they flag data quality for review.
--
-- Threshold: 25% (pmp back-calculation introduces ~1-5% rounding;
--   >25% is almost certainly a real discrepancy, not rounding noise).

{{ config(severity='warn') }}

WITH irodat_rows AS (
    SELECT
        country_iso3,
        report_year                     AS year,
        total_transplants               AS irodat_total,
        deceased_donors                 AS irodat_deceased
    FROM {{ ref('stg_irodat') }}
),

et_rows AS (
    SELECT
        country_iso3,
        report_year                     AS year,
        total_transplants               AS regional_total,
        deceased_donors                 AS regional_deceased,
        CAST('Eurotransplant' AS VARCHAR) AS regional_source
    FROM {{ ref('stg_eurotransplant') }}
),

sctp_rows AS (
    SELECT
        country_iso3,
        report_year                     AS year,
        total_transplants               AS regional_total,
        deceased_donors                 AS regional_deceased,
        CAST('Scandiatransplant' AS VARCHAR) AS regional_source
    FROM {{ ref('stg_scandiatransplant') }}
),

regional AS (
    SELECT * FROM et_rows
    UNION ALL
    SELECT * FROM sctp_rows
)

SELECT
    reg.country_iso3,
    reg.year,
    reg.regional_source,
    reg.regional_total,
    ir.irodat_total,
    reg.regional_deceased,
    ir.irodat_deceased,
    ROUND(ABS(reg.regional_total - ir.irodat_total) * 100.0 / ir.irodat_total, 1) AS pct_divergence_total
FROM regional AS reg
INNER JOIN irodat_rows AS ir
    ON ir.country_iso3 = reg.country_iso3
   AND ir.year = reg.year
WHERE reg.regional_total >= 100
  AND ir.irodat_total >= 100
  AND ABS(reg.regional_total - ir.irodat_total) * 100.0 / ir.irodat_total > 25
ORDER BY reg.country_iso3, reg.year
