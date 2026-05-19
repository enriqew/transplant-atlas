{{
  config(materialized='table')
}}

-- One row per (state_code, donation_year). Sums organ_count (donor record may
-- yield multiple organs; the staging model has already unpivoted these to one
-- row per (donor, organ) pair so we just SUM here).

WITH yearly AS (
    SELECT
        state_code,
        state_name,
        donation_year                                                AS year,
        SUM(organ_count)                                             AS donations,
        SUM(organ_count) FILTER (WHERE donor_type = 'deceased')      AS deceased_donations,
        SUM(organ_count) FILTER (WHERE donor_type = 'living')        AS living_donations
    FROM {{ ref('stg_cenatra_donations') }}
    GROUP BY
        state_code,
        state_name,
        donation_year
)

SELECT
    yearly.state_code,
    yearly.state_name,
    yearly.year,
    yearly.donations,
    yearly.deceased_donations,
    yearly.living_donations,
    population.population,
    CASE
        WHEN population.population IS NULL OR population.population = 0 THEN NULL
        ELSE ROUND(yearly.donations * 1000000.0 / population.population, 1)
    END                                                             AS donations_pmp
FROM yearly
LEFT JOIN {{ ref('dim_population_mx_state') }} AS population
    ON population.state_code = yearly.state_code
   AND population.report_year = yearly.year
