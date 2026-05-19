{{
  config(materialized='view')
}}

-- Bronze input: data/raw/population_mx/<snapshot_date>/*.csv
-- CONAPO projections come as state-by-year-by-sex-by-age rows. We aggregate to
-- (state, year) totals here for the dimension layer.
--
-- Assumed columns (verify on first run; CONAPO column names: ENTIDAD, AÑO, SEXO, EDAD, POBLACION):

WITH raw AS (
    SELECT
        UPPER(TRIM(ENTIDAD))                AS state_name_raw,
        TRY_CAST("AÑO" AS INTEGER)          AS report_year,
        TRY_CAST(POBLACION AS BIGINT)       AS population,
        filename                            AS source_filename
    FROM read_csv_auto(
        {{ latest_raw_csv_glob('population_mx') }},
        filename=true,
        ignore_errors=true,
        union_by_name=true
    )
    WHERE "AÑO" IS NOT NULL
      AND POBLACION IS NOT NULL
)

SELECT
    states.state_code,
    states.state_name,
    raw.report_year,
    SUM(raw.population)                                AS population,
    {{ snapshot_date_from_filename('MAX(raw.source_filename)') }}::DATE AS snapshot_date
FROM raw
INNER JOIN {{ ref('mx_state_codes') }} AS states
    ON states.state_name_normalized = raw.state_name_raw
GROUP BY
    states.state_code,
    states.state_name,
    raw.report_year
