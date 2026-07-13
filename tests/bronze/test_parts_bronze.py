"""
Bronze layer — Parts Catalog.

Documents known data quality issues in raw parts data:
  - PART026: negative unit_price (-500.00) from legacy pricing migration
  - PART027: missing supplier_id (supplier not yet onboarded in MDM)
  - PART028: blank part_name (ERP extract truncation bug)
  - PART030: invalid supplier reference 'SUPXXX' (orphaned from decommissioned supplier)
"""
import pytest

from src.validators.completeness_validator import CompletenessValidator
from src.validators.consistency_validator import ConsistencyValidator
from src.validators.statistical_profiler import StatisticalProfiler

pytestmark = pytest.mark.bronze

REQUIRED_COLUMNS = [
    "part_id", "part_number", "part_name", "part_category",
    "supplier_id", "unit_price", "unit_of_measure",
    "lead_time_days", "is_critical", "spec_revision", "created_date",
]

ACCEPTED_CATEGORIES = [
    "AVIONICS", "PROPULSION", "AIRFRAME", "LANDING_GEAR",
    "HYDRAULIC", "ELECTRICAL", "INTERIOR", "SAFETY",
]

ACCEPTED_UOM = ["EA", "SET", "KIT", "LB", "FT", "IN"]


class TestBronzePartsCompleteness:

    def test_required_columns_present(self, bronze_parts):
        result = CompletenessValidator(bronze_parts, "bronze_parts").check_required_columns(
            REQUIRED_COLUMNS
        )
        assert result.passed, result.summary

    def test_pk_is_unique(self, bronze_parts):
        result = CompletenessValidator(bronze_parts, "bronze_parts").check_pk_uniqueness("part_id")
        assert result.passed, f"{result.summary}\nDuplicates: {result.failures}"

    def test_row_count_in_expected_range(self, bronze_parts):
        result = CompletenessValidator(bronze_parts, "bronze_parts").check_row_count(
            min_rows=25, max_rows=200
        )
        assert result.passed, result.summary

    def test_part_number_no_nulls(self, bronze_parts):
        result = CompletenessValidator(bronze_parts, "bronze_parts").check_null_rates(
            columns=["part_number"], threshold=0.0
        )
        assert result.passed, result.summary

    def test_part_name_null_rate_within_threshold(self, bronze_parts):
        """Allow up to 5% null/empty part names — known extraction bug in PART028."""
        result = CompletenessValidator(bronze_parts, "bronze_parts").check_null_rates(
            columns=["part_name"], threshold=0.05
        )
        assert result.passed, (
            f"{result.summary}\n"
            "DQ Issue: ERP extract truncation bug — escalated to ERP team (JIRA: DQ-142)."
        )


class TestBronzePartsConsistency:

    def test_accepted_category_values(self, bronze_parts):
        result = ConsistencyValidator(bronze_parts, "bronze_parts").check_accepted_values(
            "part_category", ACCEPTED_CATEGORIES
        )
        assert result.passed, f"{result.summary}\nBad values: {result.failures}"

    def test_accepted_uom_values(self, bronze_parts):
        result = ConsistencyValidator(bronze_parts, "bronze_parts").check_accepted_values(
            "unit_of_measure", ACCEPTED_UOM
        )
        assert result.passed, f"{result.summary}\nBad values: {result.failures}"

    def test_unit_price_positive(self, bronze_parts):
        """PART026 has a negative price from legacy migration — document known count."""
        result = ConsistencyValidator(bronze_parts, "bronze_parts").check_numeric_range(
            "unit_price", min_val=0.01
        )
        max_allowed_failures = 1  # PART026 only
        assert len(result.failures) <= max_allowed_failures, (
            f"Negative price violations grew beyond accepted {max_allowed_failures}: "
            f"{len(result.failures)} found.\nDetails: {result.failures}\n"
            "DQ Issue: Legacy pricing migration error — tracked in JIRA: DQ-137."
        )

    def test_lead_time_days_positive(self, bronze_parts):
        result = ConsistencyValidator(bronze_parts, "bronze_parts").check_numeric_range(
            "lead_time_days", min_val=1, max_val=365
        )
        assert result.passed, f"{result.summary}\nBad values: {result.failures}"

    def test_created_date_format(self, bronze_parts):
        result = ConsistencyValidator(bronze_parts, "bronze_parts").check_date_format(
            "created_date", fmt="%Y-%m-%d"
        )
        assert result.passed, f"{result.summary}\nBad dates: {result.failures}"

    def test_supplier_id_null_rate(self, bronze_parts):
        """PART027 has null supplier_id — pending MDM onboarding."""
        result = CompletenessValidator(bronze_parts, "bronze_parts").check_null_rates(
            columns=["supplier_id"], threshold=0.05
        )
        assert result.passed, (
            f"{result.summary}\n"
            "DQ Issue: SUP not yet registered in MDM — tracked in JIRA: DQ-155."
        )


class TestBronzePartsStatistical:

    def test_lead_time_iqr_bounds(self, bronze_parts):
        """Flag lead times outside normal procurement cycles (IQR fence)."""
        result = StatisticalProfiler(bronze_parts, "bronze_parts").check_iqr_bounds(
            "lead_time_days", multiplier=2.5
        )
        assert result.passed, (
            f"{result.summary}\nOutliers: {result.failures}\n"
            "Review supplier contracts for unusually long lead times."
        )
