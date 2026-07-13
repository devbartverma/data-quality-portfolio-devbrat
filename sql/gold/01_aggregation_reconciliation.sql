/*
  Gold Layer — Aggregation Reconciliation
  Dialect: T-SQL (Azure Synapse / SQL Server 2019+)
  Purpose: Verify Gold production_metrics totals match Silver work order aggregations.
           Run after each Gold load as a post-load quality gate.
           A result set with rows indicates reconciliation failure.
*/

-- ============================================================
-- 1. SPEND RECONCILIATION: Silver → Gold
--    Silver source: closed + partial work orders aggregated by
--    supplier and month. Tolerance: ≤1%.
-- ============================================================
WITH silver_aggregated AS (
    SELECT
        FORMAT(TRY_CONVERT(DATE, wo.order_date), 'yyyy-MM')     AS metric_month,
        p.supplier_id,
        SUM(wo.total_cost)                                       AS silver_total_spend,
        SUM(wo.defect_count)                                     AS silver_defect_count,
        COUNT(DISTINCT wo.work_order_id)                         AS silver_order_count,
        SUM(wo.quantity_ordered)                                 AS silver_qty_ordered,
        SUM(wo.quantity_received)                                AS silver_qty_received
    FROM [silver].[work_orders_cleansed]  AS wo
    INNER JOIN [silver].[parts_catalog_cleansed] AS p
        ON wo.part_id = p.part_id
    WHERE wo.status IN ('CLOSED', 'PARTIAL')
    GROUP BY
        FORMAT(TRY_CONVERT(DATE, wo.order_date), 'yyyy-MM'),
        p.supplier_id
),

gold_metrics AS (
    SELECT
        metric_month,
        supplier_id,
        total_spend         AS gold_total_spend,
        defect_count        AS gold_defect_count,
        total_orders        AS gold_order_count,
        total_parts_ordered AS gold_qty_ordered,
        total_parts_received AS gold_qty_received
    FROM [gold].[production_metrics]
),

reconciliation AS (
    SELECT
        g.metric_month,
        g.supplier_id,
        -- Spend
        g.gold_total_spend,
        COALESCE(s.silver_total_spend, 0)                        AS silver_total_spend,
        ABS(g.gold_total_spend - COALESCE(s.silver_total_spend, 0))
                                                                 AS spend_abs_var,
        CASE
            WHEN COALESCE(s.silver_total_spend, 0) = 0 THEN NULL
            ELSE CAST(
                ABS(g.gold_total_spend - s.silver_total_spend)
                / NULLIF(s.silver_total_spend, 0) * 100 AS DECIMAL(8,4))
        END                                                      AS spend_var_pct,
        -- Defects
        g.gold_defect_count,
        COALESCE(s.silver_defect_count, 0)                       AS silver_defect_count,
        -- Orders
        g.gold_order_count,
        COALESCE(s.silver_order_count, 0)                        AS silver_order_count,
        -- DQ result
        CASE
            WHEN ABS(g.gold_total_spend - COALESCE(s.silver_total_spend, 0))
                 > COALESCE(s.silver_total_spend, 0) * 0.01
                THEN 'FAIL — spend variance > 1%'
            WHEN g.gold_defect_count <> COALESCE(s.silver_defect_count, 0)
                THEN 'FAIL — defect count mismatch'
            WHEN g.gold_order_count <> COALESCE(s.silver_order_count, 0)
                THEN 'FAIL — order count mismatch'
            WHEN s.metric_month IS NULL
                THEN 'WARN — no Silver orders for this month/supplier'
            ELSE 'PASS'
        END                                                      AS reconciliation_status
    FROM gold_metrics       AS g
    LEFT JOIN silver_aggregated AS s
        ON  g.metric_month = s.metric_month
        AND g.supplier_id  = s.supplier_id
)

SELECT *
FROM reconciliation
ORDER BY
    CASE reconciliation_status
        WHEN 'FAIL — spend variance > 1%'     THEN 1
        WHEN 'FAIL — defect count mismatch'   THEN 2
        WHEN 'FAIL — order count mismatch'    THEN 3
        WHEN 'WARN — no Silver orders for this month/supplier' THEN 4
        ELSE 5
    END,
    metric_month,
    supplier_id;
