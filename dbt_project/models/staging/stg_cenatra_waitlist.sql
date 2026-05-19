{{
  config(materialized='view')
}}

-- Bronze input: data/raw/cenatra_waitlist__*/*/*.csv
-- The waitlist dataset glob includes multiple sub-sources because the CENATRA org
-- exposes the waiting list across several CKAN packages (one per quarter or per organ).
--
-- Assumed columns (verify on first run):
--   ENTIDAD, ORGANO, FECHA_CORTE, EN_ESPERA (integer), SEXO, EDAD

WITH raw AS (
    SELECT
        UPPER(TRIM(ENTIDAD))                 AS state_name_raw,
        UPPER(TRIM(ORGANO))                  AS organ_raw,
        TRY_CAST(FECHA_CORTE AS DATE)        AS reporting_date,
        TRY_CAST(EN_ESPERA AS INTEGER)       AS persons_waiting,
        filename                             AS source_filename
    FROM read_csv_auto(
        '{{ env_var("TRANSPLANT_ATLAS_RAW_ROOT", "../data/raw") }}/cenatra_waitlist__*/*/*.csv',
        filename=true,
        ignore_errors=false
    )
),

normalized AS (
    SELECT
        states.state_code,
        states.state_name,
        organs.organ_english                                AS organ,
        raw.reporting_date,
        EXTRACT(YEAR FROM raw.reporting_date)::INTEGER      AS reporting_year,
        EXTRACT(QUARTER FROM raw.reporting_date)::INTEGER   AS reporting_quarter,
        raw.persons_waiting,
        {{ snapshot_date_from_filename('raw.source_filename') }}::DATE AS snapshot_date
    FROM raw
    LEFT JOIN {{ ref('mx_state_codes') }} AS states
        ON states.state_name_normalized = raw.state_name_raw
    LEFT JOIN {{ ref('organ_translations') }} AS organs
        ON organs.organ_spanish = raw.organ_raw
)

SELECT
    snapshot_date,
    state_code,
    state_name,
    reporting_year,
    reporting_quarter,
    reporting_date,
    organ,
    persons_waiting
FROM normalized
WHERE state_code IS NOT NULL
  AND persons_waiting IS NOT NULL
