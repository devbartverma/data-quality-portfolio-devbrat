/*
  Silver Layer — Referential Integrity Checks
  Dialect: T-SQL (Azure Synapse / SQL Server 2019+)
  Purpose: Detect orphaned foreign key references across silver tables.
           Run as part of the Silver quality gate before Gold aggregation.
*/

-- ============================================================
-- 1. PARTS → SUPPLIERS: orphaned supplier_id in silver_parts
-- ============================================================
SELECT
    'silver_parts → silver_suppliers' AS relationship,
    p.part_id,
    p.part_number,
    p.part_name,
    p.supplier_id                     AS orphaned_supplier_id,
    'Supplier not found in silver_suppliers — part must be excluded or supplier onboarded'
                                      AS remediation
FROM [silver].[parts_catalog_cleansed] AS p
LEFT JOIN [silver].[suppliers_cleansed] AS s
    ON p.supplier_id = s.supplier_id
WHERE s.supplier_id IS NULL
  AND p.supplier_id IS NOT NULL
ORDER BY p.supplier_id;

-- ============================================================
-- 2. WORK ORDERS → PARTS: orphaned part_id in silver_work_orders
-- ============================================================
SELECT
    'silver_work_orders → silver_parts' AS relationship,
    wo.work_order_id,
    wo.part_id                          AS orphaned_part_id,
    wo.status,
    wo.total_cost,
    'Part not found in silver_parts — investigate source system referential integrity'
                                        AS remediation
FROM [silver].[work_orders_cleansed] AS wo
LEFT JOIN [silver].[parts_catalog_cleansed] AS p
    ON wo.part_id = p.part_id
WHERE p.part_id IS NULL
ORDER BY wo.work_order_id;

-- ============================================================
-- 3. GOLD METRICS → SUPPLIERS: orphaned supplier_id in gold
-- ============================================================
SELECT
    'gold_metrics → silver_suppliers'   AS relationship,
    gm.metric_month,
    gm.supplier_id                      AS orphaned_supplier_id,
    gm.supplier_name,
    gm.total_spend,
    'Supplier in Gold not found in Silver — Gold aggregation may include decommissioned suppliers'
                                        AS remediation
FROM [gold].[production_metrics] AS gm
LEFT JOIN [silver].[suppliers_cleansed] AS s
    ON gm.supplier_id = s.supplier_id
WHERE s.supplier_id IS NULL
ORDER BY gm.metric_month, gm.supplier_id;

-- ============================================================
-- 4. SUMMARY REPORT
-- ============================================================
SELECT
    'parts → suppliers'     AS fk_relationship,
    COUNT(*)                AS orphaned_count
FROM [silver].[parts_catalog_cleansed] AS p
LEFT JOIN [silver].[suppliers_cleansed] AS s ON p.supplier_id = s.supplier_id
WHERE s.supplier_id IS NULL AND p.supplier_id IS NOT NULL

UNION ALL

SELECT
    'work_orders → parts',
    COUNT(*)
FROM [silver].[work_orders_cleansed] AS wo
LEFT JOIN [silver].[parts_catalog_cleansed] AS p ON wo.part_id = p.part_id
WHERE p.part_id IS NULL

UNION ALL

SELECT
    'gold_metrics → suppliers',
    COUNT(*)
FROM [gold].[production_metrics] AS gm
LEFT JOIN [silver].[suppliers_cleansed] AS s ON gm.supplier_id = s.supplier_id
WHERE s.supplier_id IS NULL;
