{{
  config(materialized='table')
}}

-- One row per (country_iso3, year). Sources ranked by authority; the lowest
-- rank wins when multiple sources cover the same country-year.
--
-- Source hierarchy:
--   1 GODT         — global, currently contributes 0 rows (PDF extraction yields
--                    only WHO regional aggregates, not country-level; kept as a
--                    placeholder for when country-level data becomes available)
--   2 ONT          — authoritative for Spain (ESP)
--   3 Eurotransplant — authoritative for AUT, BEL, HRV, DEU, HUN, NLD, SVN
--   4 IRODaT       — self-reported global coverage; fills all remaining gaps
--
-- country_name is normalised to the canonical spelling in the country_iso seed so
-- that different source spellings (e.g. "Czech Republic" vs "Czechia") are unified.

WITH combined AS (
    SELECT
        country_iso3,
        country_name,
        report_year,
        total_transplants,
        deceased_donors,
        living_donors,
        source,
        1                                                  AS source_rank
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
        3                                                  AS source_rank   -- ET: authoritative for 7 member states
    FROM {{ ref('stg_eurotransplant') }}

    UNION ALL

    SELECT
        country_iso3,
        country_name,
        report_year,
        total_transplants,
        deceased_donors,
        living_donors,
        source,
        4                                                  AS source_rank
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
    COALESCE(
        country_seed.country_name,
        deduped.country_name
    )                                                                    AS country_name,
    deduped.report_year                                                  AS year,
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
LEFT JOIN {{ ref('country_iso') }} AS country_seed
    ON country_seed.country_iso3 = deduped.country_iso3
WHERE deduped.pick = 1
