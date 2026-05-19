{{
  config(materialized='table')
}}

-- One row per (state_code, transplant_year, organ). Pre-aggregated counts plus pmp rate.
-- Joined to dim_population_mx_state to compute transplants per million population.

WITH yearly AS (
    SELECT
        state_code,
        state_name,
        transplant_year,
        organ,
        COUNT(*)                                               AS transplants,
        COUNT(*) FILTER (WHERE donor_type = 'deceased')        AS deceased_donor_transplants,
        COUNT(*) FILTER (WHERE donor_type = 'living')          AS living_donor_transplants
    FROM {{ ref('stg_cenatra_transplants') }}
    GROUP BY
        state_code,
        state_name,
        transplant_year,
        organ
)

SELECT
    yearly.state_code,
    yearly.state_name,
    yearly.transplant_year                                          AS year,
    yearly.organ,
    yearly.transplants,
    yearly.deceased_donor_transplants,
    yearly.living_donor_transplants,
    population.population,
    CASE
        WHEN population.population IS NULL OR population.population = 0 THEN NULL
        ELSE ROUND(yearly.transplants * 1000000.0 / population.population, 1)
    END                                                             AS rate_pmp
FROM yearly
LEFT JOIN {{ ref('dim_population_mx_state') }} AS population
    ON population.state_code = yearly.state_code
   AND population.report_year = yearly.transplant_year
