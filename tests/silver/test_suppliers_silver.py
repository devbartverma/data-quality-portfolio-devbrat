"""
Silver layer — Suppliers.

All tests here must PASS. Silver is the trusted, governed layer.
Failures here block downstream Gold aggregations.
"""
import pytest

from src.validators.completeness_validator import CompletenessValidator
from src.validators.consistency_validator import ConsistencyValidator
from src.validators.statistical_profiler import StatisticalProfiler

pytestmark = pytest.mark.silver

REQUIRED_COLUMNS = [
    "supplier_id", "supplier_name", "country", "email",
    "phone", "contract_start_date", "payment_terms",
    "quality_rating", "status", "source_system", "load_timestamp", "dq_load_date",
]

ACCEPTED_STATUSES = ["ACTIVE", "INACTIVE", "PROBATION", "SUSPENDED"]
ACCEPTED_PAYMENT_TERMS = ["NET30", "NET45", "NET60", "NET90"]
ACCEPTED_COUNTRIES = ["US", "FR", "GB", "CA", "DE", "JP", "AU"]

CATEGORICAL_ACCEPTED = [
    ("status", ACCEPTED_STATUSES),
    ("payment_terms", ACCEPTED_PAYMENT_TERMS),
    ("country", ACCEPTED_COUNTRIES),
]


class TestSilverSuppliersCompleteness:

    def test_required_columns_present(self, silver_suppliers):
        result = CompletenessValidator(silver_suppliers, "silver_suppliers").check_required_columns(
            REQUIRED_COLUMNS
        )
        assert result.passed, result.summary

    def test_pk_is_unique(self, silver_suppliers):
        result = CompletenessValidator(silver_suppliers, "silver_suppliers").check_pk_uniqueness(
            "supplier_id"
        )
        assert result.passed, f"{result.summary}\nDuplicates: {result.failures}"

    def test_no_nulls_on_critical_columns(self, silver_suppliers):
        """supplier_id, supplier_name, and email must be 100% populated in the governed layer."""
        validator = CompletenessValidator(silver_suppliers, "silver_suppliers")
        failures = []
        for col in ["supplier_id", "supplier_name", "email"]:
            result = validator.check_null_rates(columns=[col], threshold=0.0)
            if not result.passed:
                failures.append(result.summary)
        assert len(failures) == 0, (
            "Null violations in silver suppliers:\n" + "\n".join(failures) + "\n"
            "Re-run cleansing pipeline — silver requires 100% coverage on critical columns."
        )

    def test_row_count_in_expected_range(self, silver_suppliers):
        """Silver should have 14–16 active/probation suppliers."""
        result = CompletenessValidator(silver_suppliers, "silver_suppliers").check_row_count(
            min_rows=14, max_rows=16
        )
        assert result.passed, result.summary

    def test_no_empty_string_supplier_name(self, silver_suppliers):
        result = CompletenessValidator(silver_suppliers, "silver_suppliers").check_no_empty_strings(
            ["supplier_name", "supplier_id"]
        )
        assert result.passed, result.summary


class TestSilverSuppliersConsistency:

    def test_accepted_categorical_values(self, silver_suppliers):
        """status, payment_terms, and country must each match the governed reference list."""
        validator = ConsistencyValidator(silver_suppliers, "silver_suppliers")
        failures = []
        for col, accepted in CATEGORICAL_ACCEPTED:
            result = validator.check_accepted_values(col, accepted)
            if not result.passed:
                failures.append(f"[{col}] {result.summary}  bad_values={result.failures}")
        assert len(failures) == 0, "\n".join(failures)

    def test_quality_rating_range(self, silver_suppliers):
        result = ConsistencyValidator(silver_suppliers, "silver_suppliers").check_numeric_range(
            "quality_rating", min_val=1.0, max_val=5.0
        )
        assert result.passed, f"{result.summary}\nOut-of-range: {result.failures}"

    def test_contract_date_valid(self, silver_suppliers):
        """Silver contract dates must be ISO-8601 (DD/MM/YYYY corrected) and not in the future."""
        validator = ConsistencyValidator(silver_suppliers, "silver_suppliers")
        result = validator.check_date_format("contract_start_date", fmt="%Y-%m-%d")
        assert result.passed, (
            f"Non-ISO dates in silver: {result.failures}\n"
            "Cleansing pipeline must normalise all dates to YYYY-MM-DD."
        )
        result = validator.check_no_future_dates("contract_start_date")
        assert result.passed, f"Future contract dates detected: {result.failures}"

    def test_valid_email_format(self, silver_suppliers):
        result = ConsistencyValidator(silver_suppliers, "silver_suppliers").check_email_format(
            "email"
        )
        assert result.passed, f"{result.summary}\nBad emails: {result.failures}"

    def test_no_whitespace_padding_in_supplier_name(self, silver_suppliers):
        """Silver must have trimmed supplier names — SUP003 whitespace must be resolved."""
        result = CompletenessValidator(
            silver_suppliers, "silver_suppliers"
        ).check_no_leading_trailing_whitespace(["supplier_name"])
        assert result.passed, (
            f"{result.summary}\nPadded values: {result.failures}\n"
            "Cleansing pipeline must strip whitespace from all string columns."
        )


class TestSilverSuppliersStatistical:

    def test_categorical_column_cardinality(self, silver_suppliers):
        """quality_rating must have ≥3 distinct values; country must span 2–20 distinct codes."""
        profiler = StatisticalProfiler(silver_suppliers, "silver_suppliers")
        result = profiler.check_cardinality("quality_rating", min_distinct=3)
        assert result.passed, result.summary
        result = profiler.check_cardinality("country", min_distinct=2, max_distinct=20)
        assert result.passed, result.summary
