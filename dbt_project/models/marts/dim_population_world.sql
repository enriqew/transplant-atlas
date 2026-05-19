{{
  config(materialized='table')
}}

-- One row per (country_iso3, year). Used by world fact marts for pmp rates.

SELECT
    country_iso3,
    country_name,
    report_year,
    population
FROM {{ ref('stg_population_world') }}
