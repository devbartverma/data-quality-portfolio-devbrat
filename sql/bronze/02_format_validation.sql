/*
  Bronze Layer — Format Validation
  Target:  [bronze].[suppliers_raw], [bronze].[parts_catalog_raw]
  Dialect: T-SQL (Azure Synapse / SQL Server 2019+)
  Purpose: Detect date format anomalies, invalid email patterns, and
           out-of-range numeric values in raw source data.
*/

-- ============================================================
-- 1. DATE FORMAT ANOMALY DETECTION — contract_start_date
--    Identifies DD/MM/YYYY and other non-ISO formats
-- ============================================================
SELECT
    supplier_id,
    supplier_name,
    contract_start_date,
    CASE
        WHEN contract_start_date LIKE '[0-9][0-9]/[0-9][0-9]/[0-9][0-9][0-9][0-9]'
            THEN 'DD/MM/YYYY — needs conversion'
        WHEN contract_start_date LIKE '[0-9][0-9]-[0-9][0-9]-[0-9][0-9][0-9][0-9]'
            THEN 'DD-MM-YYYY — needs conversion'
        WHEN contract_start_date LIKE '[0-9][0-9][0-9][0-9]/[0-9][0-9]/[0-9][0-9]'
            THEN 'YYYY/MM/DD — needs conversion'
        WHEN TRY_CONVERT(DATE, contract_start_date, 23) IS NULL
            THEN 'UNPARSEABLE — manual review required'
        ELSE 'ISO 8601 YYYY-MM-DD — OK'
    END AS date_format_diagnosis,
    CASE
        WHEN TRY_CONVERT(DATE, contract_start_date, 23) IS NULL
             AND contract_start_date IS NOT NULL
            THEN 'FAIL'
        ELSE 'PASS'
    END AS dq_status
FROM [bronze].[suppliers_raw]
WHERE contract_start_date IS NOT NULL
ORDER BY dq_status DESC, supplier_id;

-- ============================================================
-- 2. EMAIL FORMAT VALIDATION
-- ============================================================
SELECT
    supplier_id,
    supplier_name,
    email,
    CASE
        WHEN email IS NULL
            THEN 'NULL — remediation required'
        WHEN email NOT LIKE '%@%.%'
            THEN 'FAIL — invalid email format'
        WHEN email LIKE '% %'
            THEN 'FAIL — contains spaces'
        ELSE 'PASS'
    END AS email_dq_status
FROM [bronze].[suppliers_raw]
ORDER BY email_dq_status DESC;

-- ============================================================
-- 3. NUMERIC RANGE VALIDATION
-- ============================================================

-- Quality rating must be 1.0 - 5.0
SELECT
    'quality_rating out of range'   AS check_name,
    supplier_id,
    supplier_name,
    quality_rating,
    'FAIL — must be between 1.0 and 5.0' AS issue
FROM [bronze].[suppliers_raw]
WHERE quality_rating < 1.0 OR quality_rating > 5.0

UNION ALL

-- Unit price must be positive
SELECT
    'unit_price non-positive'       AS check_name,
    part_id,
    part_name,
    CAST(unit_price AS VARCHAR(20)),
    'FAIL — price must be > 0'
FROM [bronze].[parts_catalog_raw]
WHERE unit_price <= 0

UNION ALL

-- Lead time must be 1-365 days
SELECT
    'lead_time_days out of range',
    part_id,
    part_name,
    CAST(lead_time_days AS VARCHAR(20)),
    'FAIL — lead time must be 1-365 days'
FROM [bronze].[parts_catalog_raw]
WHERE lead_time_days < 1 OR lead_time_days > 365

ORDER BY check_name, 2;
