{{
  config(materialized='view')
}}

-- Bronze input: data/raw/godt_world/<snapshot_date>/page_*_table_*.csv
--
-- KNOWN LIMITATION (2026-05): pdfplumber extracts ~40 "tables" from the GODT
-- annual report, but the country-level tables in that PDF render as
-- non-rectangular text blocks that pdfplumber's heuristics misclassify as
-- prose paragraphs (one cell containing multi-line text) or skip entirely.
-- The tables we DO get extracted cleanly are WHO regional aggregates
-- (AFR, AMR, EMR, EUR, SEAR, WPR), not countries.
--
-- Until a better extractor lands (pdftotext + custom parsing, or an upstream
-- machine-readable feed from GODT), this model returns the contract schema
-- with zero rows so downstream marts compile. IRODaT covers world data for
-- the meantime. See README.md "Caveats" for context.

SELECT
    CAST(NULL AS VARCHAR)  AS country_iso3,
    CAST(NULL AS VARCHAR)  AS country_name,
    CAST(NULL AS INTEGER)  AS report_year,
    CAST(NULL AS INTEGER)  AS total_transplants,
    CAST(NULL AS INTEGER)  AS deceased_donors,
    CAST(NULL AS INTEGER)  AS living_donors,
    CAST('GODT' AS VARCHAR) AS source,
    CAST(NULL AS DATE)     AS snapshot_date
WHERE 1 = 0
