{{
  config(materialized='view')
}}

-- Bronze input: data/raw/cenatra_donations/<snapshot_date>/*.csv
-- Assumed columns (verify on first run):
--   ENTIDAD, ORGANO, FECHA_DONACION, TIPO_DONANTE, ESTABLECIMIENTO
-- One raw row = one donation event.

WITH raw AS (
    SELECT
        UPPER(TRIM(ENTIDAD))             AS state_name_raw,
        UPPER(TRIM(ORGANO))              AS organ_raw,
        TRY_CAST(FECHA_DONACION AS DATE) AS donation_date,
        UPPER(TRIM(TIPO_DONANTE))        AS donor_type_raw,
        TRIM(ESTABLECIMIENTO)            AS establishment,
        filename                         AS source_filename
    FROM read_csv_auto(
        {{ latest_raw_csv_glob('cenatra_donations') }},
        filename=true,
        ignore_errors=false
    )
),

normalized AS (
    SELECT
        states.state_code,
        states.state_name,
        organs.organ_english                              AS organ,
        raw.donation_date,
        EXTRACT(YEAR FROM raw.donation_date)::INTEGER     AS donation_year,
        CASE
            WHEN raw.donor_type_raw IN ('CADAVER', 'CADAVERICO', 'FALLECIDO') THEN 'deceased'
            WHEN raw.donor_type_raw IN ('VIVO', 'VIVO RELACIONADO', 'VIVO NO RELACIONADO') THEN 'living'
            ELSE NULL
        END                                               AS donor_type,
        raw.establishment,
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
    donation_year,
    donation_date,
    organ,
    donor_type,
    establishment
FROM normalized
WHERE state_code IS NOT NULL
  AND donation_date IS NOT NULL
