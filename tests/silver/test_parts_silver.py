"""
Silver layer — Parts Catalog.

All tests must PASS. Known bronze issues (negative price, blank name,
orphaned supplier) must have been resolved in cleansing before promotion.
"""
import pytest

from src.validators.completeness_validator import CompletenessValidator
from src.validators.consistency_validator import ConsistencyValidator
from src.validators.reconciliation_validator import ReconciliationValidator
from src.validators.statistical_profiler import StatisticalProfiler

pytestmark = pytest.mark.silver

REQUIRED_COLUMNS = [
    "part_id", "part_number", "part_name", "part_category",
    "supplier_id", "unit_price", "unit_of_measure",
    "lead_time_days", "is_critical", "spec_revision", "created_date", "dq_load_date",
]

ACCEPTED_CATEGORIES = [
    "AVIONICS", "PROPULSION", "AIRFRAME", "LANDING_GEAR",
    "HYDRAULIC", "ELECTRICAL", "INTERIOR", "SAFETY",
]

ACCEPTED_UOM = ["EA", "SET", "KIT", "LB", "FT", "IN"]


class TestSilverPartsCompleteness:

    def test_required_columns_present(self, silver_parts):
        result = CompletenessValidator(silver_parts, "silver_parts").check_required_columns(
            REQUIRED_COLUMNS
        )
        assert result.passed, result.summary

    def test_pk_is_unique(self, silver_parts):
        result = CompletenessValidator(silver_parts, "silver_parts").check_pk_uniqueness("part_id")
        assert result.passed, f"{result.summary}\nDuplicates: {result.failures}"

    def test_no_nulls_on_critical_columns(self, silver_parts):
        """PART028 blank name and PART027 null supplier_id must be resolved before silver."""
        validator = CompletenessValidator(silver_parts, "silver_parts")
        hints = {
            "part_name": "Backfill from MDM or exclude the row (JIRA: DQ-142).",
            "supplier_id": "All parts in silver must reference a valid supplier (JIRA: DQ-155).",
        }
        failures = []
        for col, hint in hints.items():
            result = validator.check_null_rates(columns=[col], threshold=0.0)
            if not result.passed:
                failures.append(f"[{col}] {result.summary}  {hint}")
        assert len(failures) == 0, "\n".join(failures)

    def test_row_count_at_least_25(self, silver_parts):
        """Silver should retain ≥25 valid parts after dropping bad bronze records."""
        result = CompletenessValidator(silver_parts, "silver_parts").check_row_count(min_rows=25)
        assert result.passed, result.summary


class TestSilverPartsConsistency:

    def test_accepted_categorical_values(self, silver_parts):
        """part_category and unit_of_measure must each match the governed reference list."""
        validator = ConsistencyValidator(silver_parts, "silver_parts")
        failures = []
        for col, accepted in [("part_category", ACCEPTED_CATEGORIES), ("unit_of_measure", ACCEPTED_UOM)]:
            result = validator.check_accepted_values(col, accepted)
            if not result.passed:
                failures.append(f"[{col}] {result.summary}  bad_values={result.failures}")
        assert len(failures) == 0, "\n".join(failures)

    def test_unit_price_positive(self, silver_parts):
        """Bronze PART026 negative price must have been corrected or excluded."""
        result = ConsistencyValidator(silver_parts, "silver_parts").check_numeric_range(
            "unit_price", min_val=0.01
        )
        assert result.passed, (
            f"{result.summary}\nNegative prices: {result.failures}\n"
            "Silver must not contain negative unit prices."
        )

    def test_lead_time_positive(self, silver_parts):
        result = ConsistencyValidator(silver_parts, "silver_parts").check_numeric_range(
            "lead_time_days", min_val=1, max_val=365
        )
        assert result.passed, f"{result.summary}\nBad values: {result.failures}"

    def test_created_date_iso_format(self, silver_parts):
        result = ConsistencyValidator(silver_parts, "silver_parts").check_date_format(
            "created_date", fmt="%Y-%m-%d"
        )
        assert result.passed, f"{result.summary}\nBad dates: {result.failures}"

    def test_supplier_referential_integrity(self, silver_parts, silver_suppliers):
        """Every part's supplier_id must exist in the silver suppliers table."""
        result = ConsistencyValidator(
            silver_parts, "silver_parts"
        ).check_referential_integrity(
            fk_column="supplier_id",
            reference_df=silver_suppliers,
            pk_column="supplier_id",
            allow_null=False,
        )
        assert result.passed, (
            f"{result.summary}\nOrphaned supplier_ids: {result.failures}\n"
            "Bronze SUPXXX and null supplier_ids must not appear in silver."
        )


class TestSilverPartsReconciliation:

    def test_bronze_to_silver_row_drop_within_tolerance(self, bronze_parts, silver_parts):
        """Silver should drop at most 15% of bronze rows (known bad: PART026, 027, 028, 030)."""
        result = ReconciliationValidator(
            bronze_parts, silver_parts, "bronze_parts", "silver_parts"
        ).check_row_count_delta(max_drop_pct=15.0, max_gain_pct=0.0)
        assert result.passed, (
            f"{result.summary}\n"
            "Excessive row drop suggests cleansing pipeline is too aggressive."
        )

    def test_no_new_part_ids_introduced_in_silver(self, bronze_parts, silver_parts):
        """Silver must not introduce part_ids not present in bronze."""
        result = ReconciliationValidator(
            bronze_parts, silver_parts, "bronze_parts", "silver_parts"
        ).check_no_new_pks("part_id")
        assert result.passed, f"{result.summary}\nPhantom IDs: {result.failures}"

    def test_critical_parts_retained_in_silver(self, bronze_parts, silver_parts):
        """All is_critical=TRUE parts from bronze must be present in silver."""
        result = ReconciliationValidator(
            bronze_parts, silver_parts, "bronze_parts", "silver_parts"
        ).check_no_dropped_critical_rows(
            pk_column="part_id",
            critical_filter_column="is_critical",
            critical_value="TRUE",
        )
        assert result.passed, (
            f"{result.summary}\nDropped critical parts: {result.failures}\n"
            "Flight-critical parts must never be silently dropped in cleansing."
        )


class TestSilverPartsStatistical:

    def test_part_category_cardinality(self, silver_parts):
        """Expect at least 5 distinct part categories for a full aircraft BOM."""
        result = StatisticalProfiler(silver_parts, "silver_parts").check_cardinality(
            "part_category", min_distinct=5, max_distinct=15
        )
        assert result.passed, result.summary
