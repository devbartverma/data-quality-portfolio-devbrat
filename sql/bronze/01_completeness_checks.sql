/*
  Bronze Layer — Completeness Checks
  Target:  [bronze].[suppliers_raw], [bronze].[parts_catalog_raw]
  Dialect: T-SQL (Azure Synapse / SQL Server 2019+)
  Purpose: Identify null/blank rates per column. Run before Silver promotion.
           Results feed the DQ scorecard and trigger remediation tickets.
*/

-- ============================================================
-- 1. NULL COUNT & RATE — suppliers_raw
-- ============================================================
WITH supplier_nulls AS (
    SELECT
        'supplier_id'          AS column_name,
        COUNT(*)               AS total_rows,
        SUM(CASE WHEN supplier_id        IS NULL THEN 1 ELSE 0 END) AS null_count
    FROM [bronze].[suppliers_raw]
    UNION ALL
    SELECT 'supplier_name', COUNT(*),
        SUM(CASE WHEN supplier_name      IS NULL OR TRIM(supplier_name) = '' THEN 1 ELSE 0 END)
    FROM [bronze].[suppliers_raw]
    UNION ALL
    SELECT 'email', COUNT(*),
        SUM(CASE WHEN email              IS NULL OR TRIM(email) = '' THEN 1 ELSE 0 END)
    FROM [bronze].[suppliers_raw]
    UNION ALL
    SELECT 'country', COUNT(*),
        SUM(CASE WHEN country            IS NULL OR TRIM(country) = '' THEN 1 ELSE 0 END)
    FROM [bronze].[suppliers_raw]
    UNION ALL
    SELECT 'contract_start_date', COUNT(*),
        SUM(CASE WHEN contract_start_date IS NULL OR TRIM(CAST(contract_start_date AS VARCHAR)) = '' THEN 1 ELSE 0 END)
    FROM [bronze].[suppliers_raw]
    UNION ALL
    SELECT 'quality_rating', COUNT(*),
        SUM(CASE WHEN quality_rating     IS NULL THEN 1 ELSE 0 END)
    FROM [bronze].[suppliers_raw]
)
SELECT
    'bronze.suppliers_raw'          AS table_name,
    column_name,
    total_rows,
    null_count,
    CAST(null_count * 100.0 / NULLIF(total_rows, 0) AS DECIMAL(5,2))
                                    AS null_rate_pct,
    CASE
        WHEN column_name IN ('supplier_id', 'supplier_name', 'status') AND null_count > 0
            THEN 'FAIL — Critical column has NULLs'
        WHEN column_name = 'email' AND null_count * 100.0 / NULLIF(total_rows,0) > 10
            THEN 'FAIL — Email null rate exceeds 10% threshold'
        WHEN null_count > 0
            THEN 'WARN — NULLs detected (review)'
        ELSE 'PASS'
    END                             AS dq_status
FROM supplier_nulls
ORDER BY null_count DESC;

-- ============================================================
-- 2. NULL COUNT & RATE — parts_catalog_raw
-- ============================================================
WITH parts_nulls AS (
    SELECT 'part_id'     AS column_name, COUNT(*) AS total_rows,
        SUM(CASE WHEN part_id    IS NULL THEN 1 ELSE 0 END) AS null_count
    FROM [bronze].[parts_catalog_raw]
    UNION ALL
    SELECT 'part_number', COUNT(*),
        SUM(CASE WHEN part_number IS NULL OR TRIM(part_number) = '' THEN 1 ELSE 0 END)
    FROM [bronze].[parts_catalog_raw]
    UNION ALL
    SELECT 'part_name', COUNT(*),
        SUM(CASE WHEN part_name  IS NULL OR TRIM(part_name) = '' THEN 1 ELSE 0 END)
    FROM [bronze].[parts_catalog_raw]
    UNION ALL
    SELECT 'supplier_id', COUNT(*),
        SUM(CASE WHEN supplier_id IS NULL THEN 1 ELSE 0 END)
    FROM [bronze].[parts_catalog_raw]
    UNION ALL
    SELECT 'unit_price', COUNT(*),
        SUM(CASE WHEN unit_price  IS NULL THEN 1 ELSE 0 END)
    FROM [bronze].[parts_catalog_raw]
    UNION ALL
    SELECT 'part_category', COUNT(*),
        SUM(CASE WHEN part_category IS NULL OR TRIM(part_category) = '' THEN 1 ELSE 0 END)
    FROM [bronze].[parts_catalog_raw]
)
SELECT
    'bronze.parts_catalog_raw'      AS table_name,
    column_name,
    total_rows,
    null_count,
    CAST(null_count * 100.0 / NULLIF(total_rows, 0) AS DECIMAL(5,2))
                                    AS null_rate_pct,
    CASE
        WHEN column_name = 'part_id' AND null_count > 0
            THEN 'FAIL — PK cannot be NULL'
        WHEN null_count * 100.0 / NULLIF(total_rows,0) > 5
            THEN 'FAIL — Exceeds 5% null threshold'
        WHEN null_count > 0
            THEN 'WARN — Review nulls'
        ELSE 'PASS'
    END                             AS dq_status
FROM parts_nulls
ORDER BY null_count DESC;

-- ============================================================
-- 3. WHITESPACE PADDING CHECK — supplier names
-- ============================================================
SELECT
    supplier_id,
    supplier_name,
    LEN(supplier_name)              AS raw_length,
    LEN(TRIM(supplier_name))        AS trimmed_length,
    'Leading/trailing whitespace'   AS issue
FROM [bronze].[suppliers_raw]
WHERE LEN(supplier_name) <> LEN(TRIM(supplier_name))
ORDER BY supplier_id;
