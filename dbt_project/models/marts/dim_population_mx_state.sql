{{
  config(materialized='table')
}}

-- One row per (state_code, year). Used by fact marts for per-million-population rates.

SELECT
    state_code,
    state_name,
    report_year,
    population
FROM {{ ref('stg_population_mx') }}
