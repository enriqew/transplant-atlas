{{
  config(materialized='view')
}}

-- Bronze input: data/raw/cenatra_donations/<snapshot_date>/*.csv
-- Real schema (verified 2026-05): one row per donor (NOT per organ). Per-organ
-- columns hold integer counts of how many of that organ kind were procured.
--
--   sexo, codigo_sexo, tipo_donante, muerte,
--   entidad_federativa, codigo_entidad_federativa,
--   establecimiento, institucion, edad, fecha_procuracion,  -- DD/MM/YYYY HH:MM:SS
--   rinon_izquierdo, rinon_derecho, rinon_block,
--   pulmon_izquierdo, pulmon_derecho,
--   corazon, higado, pancreas, intestino,
--   cornea_izquierda, cornea_derecha,
--   piel, huesos, corazon_tejidos
--
-- We unpivot the organ columns into (donor, organ_raw, organ_count) rows and
-- collapse to the gold organ enum at the same time.

-- CENATRA uses 97/99 as "No Disponible" sentinels for entity codes.
WITH raw AS (
    SELECT
        NULLIF(NULLIF(TRY_CAST(codigo_entidad_federativa AS INTEGER), 97), 99)    AS cve_geo,
        TRIM(tipo_donante)                                                        AS donor_type_raw,
        TRIM(establecimiento)                                                     AS establishment,
        TRY_CAST(fecha_procuracion AS DATE)                                       AS donation_date,
        TRY_CAST(rinon_izquierdo AS INTEGER)        AS rinon_izquierdo,
        TRY_CAST(rinon_derecho AS INTEGER)          AS rinon_derecho,
        TRY_CAST(rinon_block AS INTEGER)            AS rinon_block,
        TRY_CAST(pulmon_izquierdo AS INTEGER)       AS pulmon_izquierdo,
        TRY_CAST(pulmon_derecho AS INTEGER)         AS pulmon_derecho,
        TRY_CAST(corazon AS INTEGER)                AS corazon,
        TRY_CAST(higado AS INTEGER)                 AS higado,
        TRY_CAST(pancreas AS INTEGER)               AS pancreas,
        TRY_CAST(intestino AS INTEGER)              AS intestino,
        TRY_CAST(cornea_izquierda AS INTEGER)       AS cornea_izquierda,
        TRY_CAST(cornea_derecha AS INTEGER)         AS cornea_derecha,
        TRY_CAST(piel AS INTEGER)                   AS piel,
        TRY_CAST(huesos AS INTEGER)                 AS huesos,
        TRY_CAST(corazon_tejidos AS INTEGER)        AS corazon_tejidos,
        filename                                    AS source_filename
    FROM read_csv_auto(
        {{ latest_raw_csv_glob('cenatra_donations') }},
        filename=true,
        ignore_errors=false,
        union_by_name=true
    )
),

unpivoted AS (
    SELECT cve_geo, donor_type_raw, establishment, donation_date, source_filename,
           'kidney'       AS organ, (COALESCE(rinon_izquierdo,0) + COALESCE(rinon_derecho,0) + COALESCE(rinon_block,0)) AS organ_count
    FROM raw
    UNION ALL
    SELECT cve_geo, donor_type_raw, establishment, donation_date, source_filename,
           'lung', (COALESCE(pulmon_izquierdo,0) + COALESCE(pulmon_derecho,0))
    FROM raw
    UNION ALL
    SELECT cve_geo, donor_type_raw, establishment, donation_date, source_filename,
           'heart', COALESCE(corazon,0)
    FROM raw
    UNION ALL
    SELECT cve_geo, donor_type_raw, establishment, donation_date, source_filename,
           'liver', COALESCE(higado,0)
    FROM raw
    UNION ALL
    SELECT cve_geo, donor_type_raw, establishment, donation_date, source_filename,
           'pancreas', COALESCE(pancreas,0)
    FROM raw
    UNION ALL
    SELECT cve_geo, donor_type_raw, establishment, donation_date, source_filename,
           'cornea', (COALESCE(cornea_izquierda,0) + COALESCE(cornea_derecha,0))
    FROM raw
    UNION ALL
    SELECT cve_geo, donor_type_raw, establishment, donation_date, source_filename,
           'other_tissue',
           (COALESCE(intestino,0) + COALESCE(piel,0) + COALESCE(huesos,0) + COALESCE(corazon_tejidos,0))
    FROM raw
)

SELECT
    {{ snapshot_date_from_filename('unpivoted.source_filename') }}::DATE AS snapshot_date,
    states.state_code,
    states.state_name,
    EXTRACT(YEAR FROM unpivoted.donation_date)::INTEGER      AS donation_year,
    unpivoted.donation_date,
    unpivoted.organ,
    CASE
        WHEN unpivoted.donor_type_raw ILIKE 'Cad%'        THEN 'deceased'
        WHEN unpivoted.donor_type_raw ILIKE 'Donante%'    THEN 'living'
        WHEN unpivoted.donor_type_raw ILIKE 'Vivo%'       THEN 'living'
        ELSE NULL
    END                                                      AS donor_type,
    unpivoted.establishment,
    unpivoted.organ_count
FROM unpivoted
INNER JOIN {{ ref('mx_state_codes') }} AS states
    ON states.cve_geo = unpivoted.cve_geo
WHERE unpivoted.donation_date IS NOT NULL
  AND unpivoted.organ_count > 0
