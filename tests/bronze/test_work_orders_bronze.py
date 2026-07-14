"""
Bronze layer — Work Orders.

Documents known data quality issues in raw work order data:
  - WO-2024-042: orphaned part_id 'PARTXXX' (legacy system reference)
  - WO-2024-050: status=CLOSED with null actual_delivery date
"""
import pytest

from src.validators.completeness_validator import CompletenessValidator
from src.validators.consistency_validator import ConsistencyValidator

pytestmark = pytest.mark.bronze

REQUIRED_COLUMNS = [
    "work_order_id", "part_id", "quantity_ordered", "quantity_received",
    "order_date", "expected_delivery", "actual_delivery",
    "unit_cost", "total_cost", "status", "defect_count",
    "source_system", "load_timestamp",
]

ACCEPTED_STATUSES = ["OPEN", "CLOSED", "PARTIAL", "CANCELLED"]


class TestBronzeWorkOrdersCompleteness:

    def test_required_columns_present(self, bronze_work_orders):
        result = CompletenessValidator(bronze_work_orders, "bronze_work_orders").check_required_columns(
            REQUIRED_COLUMNS
        )
        assert result.passed, result.summary

    def test_pk_is_unique(self, bronze_work_orders):
        result = CompletenessValidator(bronze_work_orders, "bronze_work_orders").check_pk_uniqueness(
            "work_order_id"
        )
        assert result.passed, f"{result.summary}\nDuplicates: {result.failures}"

    def test_row_count_in_expected_range(self, bronze_work_orders):
        result = CompletenessValidator(bronze_work_orders, "bronze_work_orders").check_row_count(
            min_rows=40, max_rows=500
        )
        assert result.passed, result.summary

    def test_part_id_no_nulls(self, bronze_work_orders):
        result = CompletenessValidator(bronze_work_orders, "bronze_work_orders").check_null_rates(
            columns=["part_id"], threshold=0.0
        )
        assert result.passed, result.summary


class TestBronzeWorkOrdersConsistency:

    def test_accepted_status_values(self, bronze_work_orders):
        """All status values must be in the approved set — detects rogue values like 'X'."""
        result = ConsistencyValidator(bronze_work_orders, "bronze_work_orders").check_accepted_values(
            "status", ACCEPTED_STATUSES
        )
        assert result.passed, (
            f"{result.summary}\nBad values: {result.failures}\n"
            "Raise DQ ticket — unexpected status value from source system."
        )

    def test_quantity_ordered_positive(self, bronze_work_orders):
        result = ConsistencyValidator(bronze_work_orders, "bronze_work_orders").check_numeric_range(
            "quantity_ordered", min_val=1
        )
        assert result.passed, f"{result.summary}\nBad values: {result.failures}"

    def test_unit_cost_positive(self, bronze_work_orders):
        result = ConsistencyValidator(bronze_work_orders, "bronze_work_orders").check_numeric_range(
            "unit_cost", min_val=0.01
        )
        assert result.passed, f"{result.summary}\nBad values: {result.failures}"

    def test_order_date_format(self, bronze_work_orders):
        result = ConsistencyValidator(bronze_work_orders, "bronze_work_orders").check_date_format(
            "order_date", fmt="%Y-%m-%d"
        )
        assert result.passed, f"{result.summary}\nBad dates: {result.failures}"

    def test_closed_orders_null_delivery_within_threshold(self, bronze_work_orders):
        """WO-2024-050 is CLOSED but has no actual_delivery — allow max 1 (JIRA: DQ-165)."""
        closed = bronze_work_orders[bronze_work_orders["status"] == "CLOSED"]
        null_delivery = closed["actual_delivery"].isna().sum()
        max_allowed = 1
        assert null_delivery <= max_allowed, (
            f"CLOSED orders with null actual_delivery grew beyond {max_allowed}: "
            f"{null_delivery} found.\n"
            "DQ Issue: CLOSED status requires a delivery date — tracked in JIRA: DQ-165."
        )
