{# Resolve a glob pattern for the most recent bronze snapshot of a given source.
   Usage in SQL:
       SELECT * FROM read_csv_auto({{ latest_raw_csv_glob('cenatra_transplants') }}, filename=true)

   The glob expands to /absolute/path/to/data/raw/<source>/<YYYY-MM-DD>/*.csv across all
   snapshot dirs; downstream models must select by the most recent date in `filename`.
#}

{% macro latest_raw_csv_glob(source) %}
  '{{ env_var("TRANSPLANT_ATLAS_RAW_ROOT", "../data/raw") }}/{{ source }}/*/*.csv'
{% endmacro %}

{% macro latest_raw_json_glob(source) %}
  '{{ env_var("TRANSPLANT_ATLAS_RAW_ROOT", "../data/raw") }}/{{ source }}/*/*.json'
{% endmacro %}

{# Helper: extract the snapshot date segment from a filename column produced by
   DuckDB's `filename=true` option on read_csv_auto. #}

{% macro snapshot_date_from_filename(filename_col) %}
  regexp_extract(replace({{ filename_col }}, chr(92), '/'), '/(\d{4}-\d{2}-\d{2})/', 1)
{% endmacro %}
