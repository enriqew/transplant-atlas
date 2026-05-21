-- Singular test (severity: warn): flag country-years where total_transplants
-- fell >50% from the prior year. Returns rows on issues detected.
--
-- Severity is 'warn' (not 'error') because IRODaT data has known anomalies
-- (Japan methodology changes, partial-year data, etc.) that don't represent
-- real pipeline failures. The goal is to surface issues for review.
--
-- Thresholds:
--   prev_transplants >= 100  — filters noise from small programs
--   current_transplants >= 10 — excludes near-zero reporting gaps not caught
--                               by the stg_irodat > 0 filter
--   threshold 50%             — genuine >50% single-year drop is almost never real
--   consecutive years only    — gaps in series are expected
--   pandemic 2020 exempted    — known global drop, not a data error

{{ config(severity='warn') }}

WITH lagged AS (
    SELECT
        country_iso3,
        country_name,
        year,
        source,
        total_transplants,
        LAG(total_transplants) OVER (
            PARTITION BY country_iso3
            ORDER BY year
        )                           AS prev_transplants,
        LAG(year) OVER (
            PARTITION BY country_iso3
            ORDER BY year
        )                           AS prev_year
    FROM {{ ref('fct_transplants_world_country_year') }}
    WHERE total_transplants IS NOT NULL
)

SELECT
    country_iso3,
    country_name,
    year,
    source,
    total_transplants                                                   AS current_transplants,
    prev_transplants,
    prev_year,
    ROUND(total_transplants * 100.0 / prev_transplants, 1)             AS pct_of_prior_year
FROM lagged
WHERE prev_transplants IS NOT NULL
  AND prev_year = year - 1
  AND prev_transplants >= 100
  AND total_transplants >= 10
  AND total_transplants < prev_transplants * 0.5
  AND year != 2020
