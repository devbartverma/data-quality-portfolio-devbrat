/*
  Gold Layer — KPI Boundary & Consistency Checks
  Dialect: T-SQL (Azure Synapse / SQL Server 2019+)
  Purpose: Validate computed KPIs for mathematical consistency and
           business-defined acceptable ranges. Failures block dashboard publish.
*/

-- ============================================================
-- 1. KPI BOUNDARY VIOLATIONS
-- ============================================================
WITH kpi_checks AS (
    SELECT
        metric_month,
        supplier_id,
        supplier_name,
        defect_rate_pct,
        on_time_delivery_pct,
        quality_score,
        total_spend,
        avg_lead_time_days,
        total_parts_ordered,
        total_parts_received,
        defect_count,

        -- Boundary flags
        CASE WHEN defect_rate_pct      < 0 OR defect_rate_pct > 100     THEN 1 ELSE 0 END AS bad_defect_rate,
        CASE WHEN on_time_delivery_pct < 0 OR on_time_delivery_pct > 100 THEN 1 ELSE 0 END AS bad_otd_pct,
        CASE WHEN quality_score        < 1 OR quality_score > 5          THEN 1 ELSE 0 END AS bad_quality_score,
        CASE WHEN total_spend          < 0                                THEN 1 ELSE 0 END AS bad_spend,
        CASE WHEN avg_lead_time_days   < 0                                THEN 1 ELSE 0 END AS bad_lead_time,
        CASE WHEN total_parts_received > total_parts_ordered              THEN 1 ELSE 0 END AS received_exceeds_ordered,
        CASE WHEN defect_count > total_parts_received                     THEN 1 ELSE 0 END AS defects_exceed_received
    FROM [gold].[production_metrics]
)
SELECT
    metric_month,
    supplier_id,
    supplier_name,
    CASE WHEN bad_defect_rate          = 1 THEN 'defect_rate_pct=' + CAST(defect_rate_pct AS VARCHAR) + ' ' ELSE '' END +
    CASE WHEN bad_otd_pct              = 1 THEN 'on_time_pct='     + CAST(on_time_delivery_pct AS VARCHAR) + ' ' ELSE '' END +
    CASE WHEN bad_quality_score        = 1 THEN 'quality_score='   + CAST(quality_score AS VARCHAR) + ' ' ELSE '' END +
    CASE WHEN bad_spend                = 1 THEN 'total_spend='     + CAST(total_spend AS VARCHAR) + ' ' ELSE '' END +
    CASE WHEN bad_lead_time            = 1 THEN 'avg_lead_time='   + CAST(avg_lead_time_days AS VARCHAR) + ' ' ELSE '' END +
    CASE WHEN received_exceeds_ordered = 1 THEN 'received>ordered ' ELSE '' END +
    CASE WHEN defects_exceed_received  = 1 THEN 'defects>received ' ELSE '' END
                                        AS violations,
    (bad_defect_rate + bad_otd_pct + bad_quality_score + bad_spend +
     bad_lead_time + received_exceeds_ordered + defects_exceed_received)
                                        AS violation_count
FROM kpi_checks
WHERE (bad_defect_rate + bad_otd_pct + bad_quality_score + bad_spend +
       bad_lead_time + received_exceeds_ordered + defects_exceed_received) > 0
ORDER BY violation_count DESC, metric_month;

-- ============================================================
-- 2. DEFECT RATE MATHEMATICAL CONSISTENCY CHECK
--    defect_rate_pct should equal defect_count / total_parts_received * 100
-- ============================================================
SELECT
    metric_month,
    supplier_id,
    supplier_name,
    defect_count,
    total_parts_received,
    defect_rate_pct                                             AS stored_defect_rate_pct,
    CAST(
        CASE WHEN total_parts_received > 0
             THEN defect_count * 100.0 / total_parts_received
             ELSE 0
        END AS DECIMAL(8,2))                                    AS computed_defect_rate_pct,
    ABS(defect_rate_pct -
        CASE WHEN total_parts_received > 0
             THEN defect_count * 100.0 / total_parts_received
             ELSE 0
        END)                                                    AS rate_discrepancy,
    CASE
        WHEN ABS(defect_rate_pct -
                 CASE WHEN total_parts_received > 0
                      THEN defect_count * 100.0 / total_parts_received
                      ELSE 0 END) > 0.1
            THEN 'FAIL — computed vs stored defect_rate mismatch'
        ELSE 'PASS'
    END                                                         AS dq_status
FROM [gold].[production_metrics]
WHERE total_parts_received > 0
ORDER BY rate_discrepancy DESC;

-- ============================================================
-- 3. SUPPLIER PERFORMANCE ALERT THRESHOLDS
--    Identify suppliers breaching SLA thresholds — feeds alert pipeline
-- ============================================================
SELECT
    metric_month,
    supplier_id,
    supplier_name,
    defect_rate_pct,
    on_time_delivery_pct,
    quality_score,
    total_spend,
    CASE
        WHEN defect_rate_pct > 20
            THEN 'CRITICAL — defect rate >' + CAST(defect_rate_pct AS VARCHAR) + '% (threshold: 20%)'
        WHEN defect_rate_pct > 10
            THEN 'WARNING — defect rate >' + CAST(defect_rate_pct AS VARCHAR) + '% (threshold: 10%)'
        ELSE 'OK'
    END AS defect_alert,
    CASE
        WHEN on_time_delivery_pct < 70
            THEN 'CRITICAL — OTD <70% (threshold: 70%)'
        WHEN on_time_delivery_pct < 85
            THEN 'WARNING — OTD <85% (threshold: 85%)'
        ELSE 'OK'
    END AS otd_alert,
    CASE
        WHEN quality_score < 3.0
            THEN 'CRITICAL — quality score <3.0 — supplier review required'
        WHEN quality_score < 3.5
            THEN 'WARNING — quality score <3.5'
        ELSE 'OK'
    END AS quality_alert
FROM [gold].[production_metrics]
WHERE defect_rate_pct > 10
   OR on_time_delivery_pct < 85
   OR quality_score < 3.5
ORDER BY defect_rate_pct DESC, metric_month;
