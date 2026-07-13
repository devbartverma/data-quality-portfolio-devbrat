/*
  Singular test: assert_silver_parts_referential_integrity

  Verifies that every supplier_id in silver_parts exists in silver_suppliers.
  Returns rows that violate referential integrity — a passing test returns 0 rows.

  This catches:
    - Bronze SUPXXX orphaned supplier that must be excluded in cleansing
    - Any newly introduced phantom supplier references
*/
SELECT
    p.part_id,
    p.part_number,
    p.supplier_id          AS orphaned_supplier_id,
    p.part_category
FROM {{ ref('silver_parts') }} AS p
LEFT JOIN {{ ref('silver_suppliers') }} AS s
    ON p.supplier_id = s.supplier_id
WHERE s.supplier_id IS NULL
  AND p.supplier_id IS NOT NULL
