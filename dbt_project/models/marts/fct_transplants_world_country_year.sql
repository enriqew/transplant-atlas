{{
  config(materialized='table')
}}

-- One row per (country_iso3, year). Unions GODT and IRODaT, preferring GODT when
-- both sources report the same country-year. Adds pmp rates from World Bank.

WITH combined AS (
    SELECT
        country_iso3,
        country_name,
        report_year,
        total_transplants,
        deceased_donors,
        living_donors,
        source,
        1                                                  AS source_rank   -- GODT preferred
    FROM {{ ref('stg_godt_world') }}

    UNION ALL

    SELECT
        country_iso3,
        country_name,
        report_year,
        total_transplants,
        deceased_donors,
        living_donors,
        source,
        2                                                  AS source_rank   -- ONT: authoritative for Spain
    FROM {{ ref('stg_ont_spain') }}

    UNION ALL

    SELECT
        country_iso3,
        country_name,
        report_year,
        total_transplants,
        deceased_donors,
        living_donors,
        source,
        3                                                  AS source_rank
    FROM {{ ref('stg_irodat') }}
),

deduped AS (
    SELECT
        country_iso3,
        country_name,
        report_year,
        total_transplants,
        deceased_donors,
        living_donors,
        source,
        ROW_NUMBER() OVER (
            PARTITION BY country_iso3, report_year
            ORDER BY source_rank
        )                                                  AS pick
    FROM combined
)

SELECT
    deduped.country_iso3,
    deduped.country_name,
    deduped.report_year                                                 AS year,
    deduped.total_transplants,
    deduped.deceased_donors,
    deduped.living_donors,
    deduped.source,
    population.population,
    CASE
        WHEN population.population IS NULL OR population.population = 0 THEN NULL
        ELSE ROUND(deduped.total_transplants * 1000000.0 / population.population, 1)
    END                                                                  AS transplants_pmp,
    CASE
        WHEN population.population IS NULL OR population.population = 0 OR deduped.deceased_donors IS NULL THEN NULL
        ELSE ROUND(deduped.deceased_donors * 1000000.0 / population.population, 1)
    END                                                                  AS deceased_donors_pmp,
    CASE
        WHEN population.population IS NULL OR population.population = 0 OR deduped.living_donors IS NULL THEN NULL
        ELSE ROUND(deduped.living_donors * 1000000.0 / population.population, 1)
    END                                                                  AS living_donors_pmp
FROM deduped
LEFT JOIN {{ ref('dim_population_world') }} AS population
    ON population.country_iso3 = deduped.country_iso3
   AND population.report_year = deduped.report_year
WHERE deduped.pick = 1
