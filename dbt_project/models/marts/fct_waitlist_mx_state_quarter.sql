{{
  config(materialized='table')
}}

-- One row per (state_code, year, quarter, organ). End-of-quarter waiting list snapshot.

SELECT
    state_code,
    state_name,
    reporting_year                                         AS year,
    reporting_quarter                                      AS quarter,
    organ,
    MAX(persons_waiting)                                   AS persons_waiting,
    MAX(reporting_date)                                    AS reporting_date_max
FROM {{ ref('stg_cenatra_waitlist') }}
GROUP BY
    state_code,
    state_name,
    reporting_year,
    reporting_quarter,
    organ
