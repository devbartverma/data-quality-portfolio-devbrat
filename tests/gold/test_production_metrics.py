"""
Gold layer — Production Metrics.

Tests validate KPI boundaries, aggregation accuracy, and business rule
compliance on the curated reporting layer.
"""
import pytest
import pandas as pd

from src.validators.completeness_validator import CompletenessValidator
from src.validators.consistency_validator import ConsistencyValidator
from src.validators.statistical_profiler import StatisticalProfiler

pytestmark = pytest.mark.gold

REQUIRED_COLUMNS = [
    "metric_month", "supplier_id", "supplier_name",
    "total_orders", "total_parts_ordered", "total_parts_received",
    "total_spend", "defect_count", "defect_rate_pct",
    "on_time_delivery_count", "on_time_delivery_pct",
    "avg_lead_time_days", "quality_score", "dq_load_date",
]

KPI_BOUNDS = [
    ("defect_rate_pct", 0.0, 100.0),
    ("on_time_delivery_pct", 0.0, 100.0),
    ("quality_score", 1.0, 5.0),
    ("total_spend", 0.0, None),
    ("avg_lead_time_days", 0.0, None),
]


class TestGoldMetricsCompleteness:

    def test_required_columns_present(self, gold_metrics):
        result = CompletenessValidator(gold_metrics, "gold_metrics").check_required_columns(
            REQUIRED_COLUMNS
        )
        assert result.passed, result.summary

    def test_no_null_supplier_id(self, gold_metrics):
        result = CompletenessValidator(gold_metrics, "gold_metrics").check_null_rates(
            columns=["supplier_id", "metric_month"], threshold=0.0
        )
        assert result.passed, result.summary

    def test_row_count_positive(self, gold_metrics):
        result = CompletenessValidator(gold_metrics, "gold_metrics").check_row_count(min_rows=5)
        assert result.passed, result.summary

    def test_composite_pk_unique(self, gold_metrics):
        """(metric_month, supplier_id) must be unique — no duplicate monthly rows per supplier."""
        dupes = gold_metrics.duplicated(subset=["metric_month", "supplier_id"], keep=False)
        assert dupes.sum() == 0, (
            f"{dupes.sum()} duplicate (metric_month, supplier_id) combinations found:\n"
            f"{gold_metrics[dupes][['metric_month', 'supplier_id']]}"
        )


class TestGoldMetricsKPIBoundaries:

    def test_kpi_numeric_boundaries(self, gold_metrics):
        """All KPI columns must stay within their defined operational bounds."""
        validator = ConsistencyValidator(gold_metrics, "gold_metrics")
        failures = []
        for col, min_val, max_val in KPI_BOUNDS:
            result = validator.check_numeric_range(col, min_val=min_val, max_val=max_val)
            if not result.passed:
                failures.append(f"[{col}] {result.summary}")
        assert len(failures) == 0, "\n".join(failures)

    def test_inventory_business_constraints(self, gold_metrics):
        """Parts received cannot exceed ordered; defect count cannot exceed parts received."""
        failures = []
        over_received = gold_metrics[
            gold_metrics["total_parts_received"] > gold_metrics["total_parts_ordered"]
        ]
        if len(over_received) > 0:
            failures.append(
                f"received > ordered in {len(over_received)} row(s):\n"
                f"{over_received[['metric_month', 'supplier_id', 'total_parts_ordered', 'total_parts_received']].to_string()}"
            )
        over_defect = gold_metrics[
            gold_metrics["defect_count"] > gold_metrics["total_parts_received"]
        ]
        if len(over_defect) > 0:
            failures.append(
                f"defect_count > total_parts_received in {len(over_defect)} row(s):\n"
                f"{over_defect[['metric_month', 'supplier_id', 'defect_count', 'total_parts_received']].to_string()}"
            )
        assert len(failures) == 0, "\n".join(failures)

    def test_metric_month_format(self, gold_metrics):
        result = ConsistencyValidator(gold_metrics, "gold_metrics").check_date_format(
            "metric_month", fmt="%Y-%m"
        )
        assert result.passed, f"{result.summary}\nBad months: {result.failures}"

    def test_supplier_referential_integrity(self, gold_metrics, silver_suppliers):
        """Gold supplier_ids must exist in silver suppliers."""
        result = ConsistencyValidator(
            gold_metrics, "gold_metrics"
        ).check_referential_integrity(
            fk_column="supplier_id",
            reference_df=silver_suppliers,
            pk_column="supplier_id",
            allow_null=False,
        )
        assert result.passed, f"{result.summary}\nOrphaned: {result.failures}"


class TestGoldMetricsAggregationAccuracy:

    def test_defect_rate_computed_correctly(self, gold_metrics):
        """Validate: defect_rate_pct = defect_count / total_parts_received * 100 (±0.1%)."""
        non_zero = gold_metrics[gold_metrics["total_parts_received"] > 0].copy()
        non_zero["expected_rate"] = (
            non_zero["defect_count"] / non_zero["total_parts_received"] * 100
        ).round(2)
        non_zero["actual_rate"] = non_zero["defect_rate_pct"].round(2)
        mismatches = non_zero[
            (non_zero["expected_rate"] - non_zero["actual_rate"]).abs() > 0.1
        ]
        assert len(mismatches) == 0, (
            f"{len(mismatches)} row(s) with incorrect defect_rate_pct:\n"
            f"{mismatches[['metric_month', 'supplier_id', 'expected_rate', 'actual_rate']]}"
        )


class TestGoldMetricsStatistical:

    def test_quality_score_cardinality(self, gold_metrics):
        """Quality score should have meaningful spread — not all 5.0."""
        result = StatisticalProfiler(gold_metrics, "gold_metrics").check_cardinality(
            "quality_score", min_distinct=2
        )
        assert result.passed, result.summary
