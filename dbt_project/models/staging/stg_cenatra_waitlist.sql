{{
  config(materialized='view')
}}

-- Bronze input: data/raw/cenatra_waitlist__pacientes_espera_organo_tejido/<snapshot_date>/*.csv
-- Real schema (verified 2026-05). One row per patient on the waiting list at the
-- end of the reporting quarter:
--   sexo, codigo_sexo, grupo_sanguineo, rh,
--   fecha_nacimiento, fecha_registro_comite,        -- DD/MM/YYYY HH:MM:SS
--   organo, origen_injerto,
--   establecimiento, institucion,
--   entidad_federativa_establecimiento, codigo_entidad_federativa_establecimiento,
--   estado_origen_paciente,    codigo_entidad_federativa_origen_paciente,
--   estado_residencia_paciente, codigo_entidad_federativa_residencia_paciente
--
-- Each quarterly file is a snapshot at end-of-quarter. We parse the reporting period
-- from the filename (e.g. "4toTrimestre2025") to set (reporting_year, reporting_quarter).
-- Patient count per (state, organ, year, quarter) becomes persons_waiting in gold.

-- CENATRA uses 97/99 as "No Disponible" sentinels for entity codes.
WITH raw AS (
    SELECT
        NULLIF(NULLIF(TRY_CAST(codigo_entidad_federativa_residencia_paciente AS INTEGER), 97), 99) AS cve_geo_residence,
        NULLIF(NULLIF(TRY_CAST(codigo_entidad_federativa_establecimiento AS INTEGER), 97), 99)     AS cve_geo_establishment,
        UPPER(TRIM(organo))                                                                         AS organ_raw,
        filename                                                                                    AS source_filename
    FROM read_csv_auto(
        '{{ env_var("TRANSPLANT_ATLAS_RAW_ROOT", "../data/raw") }}/cenatra_waitlist__pacientes_espera_organo_tejido/*/*.csv',
        filename=true,
        ignore_errors=false,
        union_by_name=true
    )
),

with_period AS (
    SELECT
        COALESCE(raw.cve_geo_residence, raw.cve_geo_establishment) AS cve_geo,
        raw.organ_raw,
        raw.source_filename,
        CASE
            WHEN raw.source_filename ILIKE '%1erTrimestre%' THEN 1
            WHEN raw.source_filename ILIKE '%2doTrimestre%' THEN 2
            WHEN raw.source_filename ILIKE '%3erTrimestre%' THEN 3
            WHEN raw.source_filename ILIKE '%4toTrimestre%' THEN 4
            ELSE NULL
        END                                                       AS reporting_quarter,
        TRY_CAST(regexp_extract(raw.source_filename, 'Trimestre(\d{4})', 1) AS INTEGER) AS reporting_year
    FROM raw
)

SELECT
    {{ snapshot_date_from_filename('with_period.source_filename') }}::DATE AS snapshot_date,
    states.state_code,
    states.state_name,
    with_period.reporting_year,
    with_period.reporting_quarter,
    -- End of quarter as a date — used only for ORDER BY downstream, not for joins.
    CASE with_period.reporting_quarter
        WHEN 1 THEN MAKE_DATE(with_period.reporting_year, 3, 31)
        WHEN 2 THEN MAKE_DATE(with_period.reporting_year, 6, 30)
        WHEN 3 THEN MAKE_DATE(with_period.reporting_year, 9, 30)
        WHEN 4 THEN MAKE_DATE(with_period.reporting_year, 12, 31)
    END                                                          AS reporting_date,
    organs.organ_english                                         AS organ
FROM with_period
INNER JOIN {{ ref('mx_state_codes') }} AS states
    ON states.cve_geo = with_period.cve_geo
LEFT JOIN {{ ref('organ_translations') }} AS organs
    ON organs.organ_spanish = with_period.organ_raw
WHERE with_period.reporting_year IS NOT NULL
  AND with_period.reporting_quarter IS NOT NULL
  AND organs.organ_english IS NOT NULL
