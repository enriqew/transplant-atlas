{{
  config(materialized='view')
}}

-- Bronze input: data/raw/cenatra_transplants/<snapshot_date>/*.csv
-- Assumed columns (verify on first run; adjust if upstream renames):
--   ENTIDAD              - state in Spanish, upper-case
--   ORGANO               - organ in Spanish, upper-case
--   SEXO                 - 'HOMBRE' | 'MUJER'
--   EDAD                 - integer years
--   FECHA_TRASPLANTE     - YYYY-MM-DD
--   ESTABLECIMIENTO      - hospital name
--   TIPO_DONANTE         - 'VIVO' | 'CADAVER' (deceased)
-- Each raw row represents one transplant procedure.

WITH raw AS (
    SELECT
        UPPER(TRIM(ENTIDAD))             AS state_name_raw,
        UPPER(TRIM(ORGANO))              AS organ_raw,
        UPPER(TRIM(SEXO))                AS sex_raw,
        TRY_CAST(EDAD AS INTEGER)        AS age_years,
        TRY_CAST(FECHA_TRASPLANTE AS DATE) AS transplant_date,
        TRIM(ESTABLECIMIENTO)            AS establishment,
        UPPER(TRIM(TIPO_DONANTE))        AS donor_type_raw,
        filename                         AS source_filename
    FROM read_csv_auto(
        {{ latest_raw_csv_glob('cenatra_transplants') }},
        filename=true,
        ignore_errors=false
    )
),

normalized AS (
    SELECT
        raw.state_name_raw,
        raw.organ_raw,
        raw.sex_raw,
        raw.age_years,
        raw.transplant_date,
        raw.establishment,
        raw.donor_type_raw,
        states.state_code,
        states.state_name,
        organs.organ_english                              AS organ,
        CASE
            WHEN raw.donor_type_raw IN ('CADAVER', 'CADAVERICO', 'FALLECIDO') THEN 'deceased'
            WHEN raw.donor_type_raw IN ('VIVO', 'VIVO RELACIONADO', 'VIVO NO RELACIONADO') THEN 'living'
            ELSE NULL
        END                                               AS donor_type,
        {{ snapshot_date_from_filename('raw.source_filename') }}::DATE AS snapshot_date,
        EXTRACT(YEAR FROM raw.transplant_date)::INTEGER   AS transplant_year
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
    transplant_year,
    transplant_date,
    organ,
    organ_raw,
    sex_raw,
    age_years,
    establishment,
    donor_type
FROM normalized
WHERE state_code IS NOT NULL
  AND organ IS NOT NULL
  AND transplant_date IS NOT NULL
