"""Gold layer SQL validation — KPI boundaries, aggregation accuracy, and FK integrity.

Mirrors sql/gold/01_aggregation_reconciliation.sql and sql/gold/02_kpi_boundary_checks.sql
but runs live in CI via DuckDB against production_metrics.csv.

Failure here means Gold KPIs are corrupted — the BI dashboard must not be refreshed
until all checks pass.
"""
import pytest

pytestmark = pytest.mark.sql


class TestGoldMetricsSQL:
    """KPI boundary checks, aggregation math, and lineage integrity on production_metrics."""

    def test_composite_pk_unique(self, duckdb_con):
        """(metric_month, supplier_id) must be unique — duplicates cause double-counted KPIs."""
        dupes = duckdb_con.execute(
            """
            SELECT metric_month, supplier_id, COUNT(*) AS cnt
            FROM gold_metrics
            GROUP BY metric_month, supplier_id
            HAVING COUNT(*) > 1
            ORDER BY cnt DESC
            """
        ).fetchall()
        assert len(dupes) == 0, f"Duplicate (metric_month, supplier_id) rows in gold: {dupes}"

    def test_no_negative_defect_count(self, duckdb_con):
        count = duckdb_con.execute(
            "SELECT COUNT(*) FROM gold_metrics WHERE defect_count < 0"
        ).fetchone()[0]
        assert count == 0, f"{count} row(s) have negative defect_count in gold"

    def test_defect_rate_within_bounds(self, duckdb_con):
        """defect_rate_pct must be 0–100 — a rate outside this range means pipeline arithmetic error."""
        count = duckdb_con.execute(
            """
            SELECT COUNT(*) FROM gold_metrics
            WHERE CAST(defect_rate_pct AS DOUBLE) < 0
               OR CAST(defect_rate_pct AS DOUBLE) > 100
            """
        ).fetchone()[0]
        assert count == 0, f"{count} row(s) have defect_rate_pct outside 0–100"

    def test_delivery_pct_within_bounds(self, duckdb_con):
        """on_time_delivery_pct must be 0–100."""
        count = duckdb_con.execute(
            """
            SELECT COUNT(*) FROM gold_metrics
            WHERE CAST(on_time_delivery_pct AS DOUBLE) < 0
               OR CAST(on_time_delivery_pct AS DOUBLE) > 100
            """
        ).fetchone()[0]
        assert count == 0, f"{count} row(s) have on_time_delivery_pct outside 0–100"

    def test_parts_received_leq_ordered(self, duckdb_con):
        """total_parts_received cannot exceed total_parts_ordered — violates supply chain logic."""
        count = duckdb_con.execute(
            "SELECT COUNT(*) FROM gold_metrics WHERE total_parts_received > total_parts_ordered"
        ).fetchone()[0]
        assert count == 0, f"{count} row(s) where total_parts_received > total_parts_ordered"

    def test_defect_count_leq_parts_received(self, duckdb_con):
        """Defect count cannot exceed total parts received."""
        count = duckdb_con.execute(
            "SELECT COUNT(*) FROM gold_metrics WHERE defect_count > total_parts_received"
        ).fetchone()[0]
        assert count == 0, f"{count} row(s) where defect_count > total_parts_received"

    def test_gold_supplier_fk_to_silver(self, duckdb_con):
        """All Gold supplier_ids must exist in Silver — detects phantom or injected records."""
        orphans = duckdb_con.execute(
            """
            SELECT DISTINCT g.supplier_id
            FROM gold_metrics g
            LEFT JOIN silver_suppliers s ON g.supplier_id = s.supplier_id
            WHERE s.supplier_id IS NULL
            ORDER BY g.supplier_id
            """
        ).fetchall()
        assert len(orphans) == 0, (
            f"Gold has supplier_ids absent from silver: {orphans}\n"
            "This indicates phantom records injected into the Gold layer bypassing the Silver gate."
        )

    def test_defect_rate_pct_math_consistency(self, duckdb_con):
        """defect_rate_pct must equal defect_count / total_parts_received × 100 within ±1%.

        Mirrors the reconciliation CTE in sql/gold/01_aggregation_reconciliation.sql.
        Failures mean the aggregation pipeline used inconsistent inputs.
        """
        violations = duckdb_con.execute(
            """
            SELECT
                metric_month,
                supplier_id,
                defect_count,
                total_parts_received,
                CAST(defect_rate_pct AS DOUBLE)                                    AS stored_rate,
                ROUND(defect_count * 100.0 / NULLIF(total_parts_received, 0), 2)  AS expected_rate,
                ABS(CAST(defect_rate_pct AS DOUBLE)
                    - defect_count * 100.0 / NULLIF(total_parts_received, 0))     AS diff
            FROM gold_metrics
            WHERE total_parts_received > 0
              AND ABS(CAST(defect_rate_pct AS DOUBLE)
                      - defect_count * 100.0 / NULLIF(total_parts_received, 0)) > 1.0
            ORDER BY diff DESC
            """
        ).fetchall()
        assert len(violations) == 0, (
            f"defect_rate_pct math is inconsistent in {len(violations)} row(s):\n"
            + "\n".join(
                f"  {month} / {sup}: stored={rate:.2f}% expected={exp:.2f}% diff={diff:.2f}%"
                for month, sup, _dc, _tr, rate, exp, diff in violations
            )
        )

    def test_total_spend_non_negative(self, duckdb_con):
        """total_spend must be ≥ 0 — zero is valid for months with no closed orders.

        Negative spend would indicate a pipeline arithmetic error and must never appear.
        """
        count = duckdb_con.execute(
            "SELECT COUNT(*) FROM gold_metrics WHERE CAST(total_spend AS DOUBLE) < 0"
        ).fetchone()[0]
        assert count == 0, f"{count} gold row(s) have negative total_spend — pipeline arithmetic error"

    def test_quality_score_in_range(self, duckdb_con):
        """quality_score must be 0.0–5.0 — matches the supplier rating scale used in Silver."""
        count = duckdb_con.execute(
            """
            SELECT COUNT(*) FROM gold_metrics
            WHERE CAST(quality_score AS DOUBLE) < 0
               OR CAST(quality_score AS DOUBLE) > 5.0
            """
        ).fetchone()[0]
        assert count == 0, f"{count} row(s) have quality_score outside 0.0–5.0 in gold"
