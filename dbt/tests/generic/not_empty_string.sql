{% test not_empty_string(model, column_name) %}
/*
  Custom generic test: assert that no row contains an empty or whitespace-only string.
  Usage in schema.yml:
      - not_empty_string
*/
SELECT {{ column_name }}
FROM {{ model }}
WHERE TRIM(CAST({{ column_name }} AS VARCHAR)) = ''
  AND {{ column_name }} IS NOT NULL
{% endtest %}
