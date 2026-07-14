{{ config(severity='warn') }}
/*
  Singular test: assert_gold_metrics_reconciliation

  Validates that Gold total_spend aggregations reconcile with Silver work order totals
  (closed + partial orders only) within a 1% tolerance per supplier per month.

  Returns rows where the variance exceeds tolerance.
  Severity is WARN: discrepancies are flagged for investigation but do not block the run.
  In production this would trigger a DQ ticket before the dashboard is refreshed.
*/
WITH silver_aggregated AS (
    SELECT
        strftime('%Y-%m', CAST(wo.order_date AS DATE)) AS metric_month,
        p.supplier_id,
        SUM(wo.total_cost)               AS silver_total_spend,
        SUM(wo.defect_count)             AS silver_defect_count,
        COUNT(DISTINCT wo.work_order_id) AS silver_order_count
    FROM {{ ref('silver_work_orders') }}  AS wo
    INNER JOIN {{ ref('silver_parts') }}  AS p ON wo.part_id = p.part_id
    WHERE wo.status IN ('CLOSED', 'PARTIAL')
    GROUP BY
        strftime('%Y-%m', CAST(wo.order_date AS DATE)),
        p.supplier_id
),

gold_metrics AS (
    SELECT
        metric_month,
        supplier_id,
        total_spend  AS gold_total_spend,
        defect_count AS gold_defect_count,
        total_orders AS gold_order_count
    FROM {{ ref('gold_production_metrics') }}
)

SELECT
    g.metric_month,
    g.supplier_id,
    g.gold_total_spend,
    COALESCE(s.silver_total_spend, 0)                             AS silver_total_spend,
    ABS(g.gold_total_spend - COALESCE(s.silver_total_spend, 0))  AS abs_variance,
    CASE
        WHEN COALESCE(s.silver_total_spend, 0) = 0 THEN NULL
        ELSE ABS(g.gold_total_spend - s.silver_total_spend)
             / NULLIF(s.silver_total_spend, 0) * 100
    END                                                           AS variance_pct
FROM gold_metrics AS g
LEFT JOIN silver_aggregated AS s
    ON  g.metric_month = s.metric_month
    AND g.supplier_id  = s.supplier_id
WHERE
    ABS(g.gold_total_spend - COALESCE(s.silver_total_spend, 0))
        > (COALESCE(s.silver_total_spend, 0) * 0.01)
    AND COALESCE(s.silver_total_spend, 0) > 0
