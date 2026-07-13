/*
  Silver Layer — Business Rules Validation
  Dialect: T-SQL (Azure Synapse / SQL Server 2019+)
  Purpose: Enforce domain-specific business rules on cleansed silver data.
           All violations should have been resolved before Silver promotion.
*/

-- ============================================================
-- 1. SUPPLIER BUSINESS RULES
-- ============================================================

-- Rule: quality_rating must be between 1.0 and 5.0
SELECT
    'BR-SUP-001: quality_rating range'  AS business_rule,
    supplier_id,
    supplier_name,
    quality_rating,
    'FAIL — must be 1.0 ≤ rating ≤ 5.0' AS violation_detail
FROM [silver].[suppliers_cleansed]
WHERE quality_rating < 1.0 OR quality_rating > 5.0

UNION ALL

-- Rule: payment_terms must be from approved list
SELECT
    'BR-SUP-002: payment_terms accepted values',
    supplier_id,
    supplier_name,
    payment_terms,
    'FAIL — ' + ISNULL(payment_terms, 'NULL') + ' is not an approved payment term'
FROM [silver].[suppliers_cleansed]
WHERE payment_terms NOT IN ('NET30', 'NET45', 'NET60', 'NET90')

UNION ALL

-- Rule: contract_start_date must not be in the future
SELECT
    'BR-SUP-003: contract_start_date not future',
    supplier_id,
    supplier_name,
    CAST(contract_start_date AS VARCHAR),
    'FAIL — contract date is in the future: ' + CAST(contract_start_date AS VARCHAR)
FROM [silver].[suppliers_cleansed]
WHERE TRY_CONVERT(DATE, contract_start_date) > CAST(GETDATE() AS DATE)

ORDER BY business_rule, supplier_id;


-- ============================================================
-- 2. PARTS BUSINESS RULES
-- ============================================================
SELECT
    'BR-PART-001: unit_price positive'  AS business_rule,
    part_id,
    part_name,
    CAST(unit_price AS VARCHAR(30))     AS column_value,
    'FAIL — unit_price must be > 0'     AS violation_detail
FROM [silver].[parts_catalog_cleansed]
WHERE unit_price <= 0

UNION ALL

SELECT
    'BR-PART-002: lead_time_days valid range',
    part_id,
    part_name,
    CAST(lead_time_days AS VARCHAR),
    'FAIL — lead_time must be 1 ≤ days ≤ 365'
FROM [silver].[parts_catalog_cleansed]
WHERE lead_time_days < 1 OR lead_time_days > 365

UNION ALL

SELECT
    'BR-PART-003: is_critical populated',
    part_id,
    part_name,
    CAST(is_critical AS VARCHAR),
    'FAIL — is_critical cannot be NULL for any part'
FROM [silver].[parts_catalog_cleansed]
WHERE is_critical IS NULL

ORDER BY business_rule, part_id;


-- ============================================================
-- 3. WORK ORDER BUSINESS RULES
-- ============================================================
SELECT
    'BR-WO-001: received ≤ ordered'     AS business_rule,
    work_order_id,
    part_id,
    CAST(quantity_ordered AS VARCHAR) + ' ordered, '
        + CAST(quantity_received AS VARCHAR) + ' received' AS column_value,
    'FAIL — cannot receive more than ordered' AS violation_detail
FROM [silver].[work_orders_cleansed]
WHERE quantity_received > quantity_ordered

UNION ALL

SELECT
    'BR-WO-002: CLOSED orders must have actual_delivery',
    work_order_id,
    part_id,
    CAST(actual_delivery AS VARCHAR),
    'FAIL — CLOSED work orders must have an actual_delivery date'
FROM [silver].[work_orders_cleansed]
WHERE status = 'CLOSED'
  AND actual_delivery IS NULL

ORDER BY business_rule, work_order_id;
