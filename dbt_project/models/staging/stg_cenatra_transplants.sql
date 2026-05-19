{{
  config(materialized='view')
}}

-- Bronze input: data/raw/cenatra_transplants/<snapshot_date>/*.csv
-- Real schema (verified 2026-05 against datos.gob.mx files):
--   sexo, codigo_sexo, institucion,
--   entidad_federativa_trasplante, codigo_entidad_federativa_trasplante,
--   establecimiento, institucion_organo,
--   entidad_federativa_organo, codigo_entidad_federativa_organo,
--   entidad_federativa_origen, codigo_entidad_federativa_origen,
--   entidad_federativa_residencia, codigo_entidad_federativa_residencia,
--   grupo_sanguineo_receptor, rh, edad_al_trasplante_anios,
--   fecha_registro_comite, fecha_trasplante,  -- both DD/MM/YYYY HH:MM:SS
--   organo,                                   -- "Córnea", "Riñón", ...
--   tipo_trasplante,                          -- "Cadáver" | "Donante en Vida" | ...
--   relacion, resultado_24hrs
--
-- One raw row = one transplant procedure. We attribute the procedure to the patient's
-- residence state when available, falling back to the transplant-establishment state.

WITH raw AS (
    SELECT
        TRY_CAST(codigo_entidad_federativa_residencia AS INTEGER)                AS cve_geo_residence,
        TRY_CAST(codigo_entidad_federativa_trasplante AS INTEGER)                AS cve_geo_establishment,
        TRIM(organo)                                                             AS organ_raw,
        TRY_CAST(fecha_trasplante AS DATE)                                       AS transplant_date,
        TRIM(establecimiento)                                                    AS establishment,
        TRIM(tipo_trasplante)                                                    AS donor_type_raw,
        UPPER(TRIM(sexo))                                                        AS sex_raw,
        TRY_CAST(edad_al_trasplante_anios AS INTEGER)                            AS age_years,
        filename                                                                 AS source_filename
    FROM read_csv_auto(
        {{ latest_raw_csv_glob('cenatra_transplants') }},
        filename=true,
        ignore_errors=false,
        union_by_name=true
    )
),

attributed AS (
    SELECT
        COALESCE(raw.cve_geo_residence, raw.cve_geo_establishment) AS cve_geo,
        raw.organ_raw,
        raw.transplant_date,
        raw.establishment,
        raw.donor_type_raw,
        raw.sex_raw,
        raw.age_years,
        raw.source_filename
    FROM raw
)

SELECT
    {{ snapshot_date_from_filename('attributed.source_filename') }}::DATE AS snapshot_date,
    states.state_code,
    states.state_name,
    EXTRACT(YEAR FROM attributed.transplant_date)::INTEGER  AS transplant_year,
    attributed.transplant_date,
    organs.organ_english                                    AS organ,
    attributed.organ_raw,
    attributed.sex_raw,
    attributed.age_years,
    attributed.establishment,
    CASE
        WHEN attributed.donor_type_raw ILIKE 'Cad%'        THEN 'deceased'
        WHEN attributed.donor_type_raw ILIKE 'Donante%'    THEN 'living'
        WHEN attributed.donor_type_raw ILIKE 'Vivo%'       THEN 'living'
        WHEN attributed.donor_type_raw ILIKE 'Fallecido%'  THEN 'deceased'
        ELSE NULL
    END                                                     AS donor_type
FROM attributed
INNER JOIN {{ ref('mx_state_codes') }} AS states
    ON states.cve_geo = attributed.cve_geo
LEFT JOIN {{ ref('organ_translations') }} AS organs
    ON organs.organ_spanish = attributed.organ_raw
WHERE attributed.transplant_date IS NOT NULL
  AND organs.organ_english IS NOT NULL
