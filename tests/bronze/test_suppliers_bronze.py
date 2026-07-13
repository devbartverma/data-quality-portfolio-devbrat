"""
Bronze layer — Suppliers.

These tests validate raw ingested data and are *expected* to detect issues.
Failures here gate promotion to the Silver layer and trigger root-cause tickets.
"""
import pytest

from src.validators.completeness_validator import CompletenessValidator
from src.validators.consistency_validator import ConsistencyValidator

pytestmark = pytest.mark.bronze

REQUIRED_COLUMNS = [
    "supplier_id", "supplier_name", "country", "email",
    "phone", "contract_start_date", "payment_terms",
    "quality_rating", "status", "source_system", "load_timestamp",
]

ACCEPTED_STATUSES = ["ACTIVE", "INACTIVE", "PROBATION", "SUSPENDED"]
ACCEPTED_PAYMENT_TERMS = ["NET30", "NET45", "NET60", "NET90"]


class TestBronzeSuppliersCompleteness:

    def test_required_columns_present(self, bronze_suppliers):
        result = CompletenessValidator(bronze_suppliers, "bronze_suppliers").check_required_columns(
            REQUIRED_COLUMNS
        )
        assert result.passed, result.summary

    def test_pk_is_unique(self, bronze_suppliers):
        result = CompletenessValidator(bronze_suppliers, "bronze_suppliers").check_pk_uniqueness(
            "supplier_id"
        )
        assert result.passed, f"{result.summary}\nDuplicates: {result.failures}"

    def test_row_count_meets_minimum(self, bronze_suppliers):
        """Expect at least 10 supplier records in raw feed."""
        result = CompletenessValidator(bronze_suppliers, "bronze_suppliers").check_row_count(
            min_rows=10
        )
        assert result.passed, result.summary

    def test_supplier_name_no_nulls(self, bronze_suppliers):
        result = CompletenessValidator(bronze_suppliers, "bronze_suppliers").check_null_rates(
            columns=["supplier_name"], threshold=0.0
        )
        assert result.passed, result.summary

    def test_supplier_id_no_nulls(self, bronze_suppliers):
        result = CompletenessValidator(bronze_suppliers, "bronze_suppliers").check_null_rates(
            columns=["supplier_id"], threshold=0.0
        )
        assert result.passed, result.summary

    def test_email_null_rate_within_threshold(self, bronze_suppliers):
        """Bronze allows up to 15% null emails — SUP006 (procurement gap) and SUP999 (ghost record).
        Anything beyond 2 known nulls triggers a new remediation ticket."""
        result = CompletenessValidator(bronze_suppliers, "bronze_suppliers").check_null_rates(
            columns=["email"], threshold=0.15
        )
        assert result.passed, (
            f"{result.summary}\n"
            "Action: Raise data remediation ticket to source system owner (ERP_SAP)."
        )


class TestBronzeSuppliersConsistency:

    def test_accepted_status_values(self, bronze_suppliers):
        """SUP999 ghost record has status='LEGACY_SYSTEM' — allow max 1 violation (JIRA: DQ-145)."""
        result = ConsistencyValidator(bronze_suppliers, "bronze_suppliers").check_accepted_values(
            "status", ACCEPTED_STATUSES
        )
        max_allowed = 1
        assert len(result.failures) <= max_allowed, (
            f"Status violations grew beyond accepted {max_allowed}: "
            f"{len(result.failures)} found.\nBad values: {result.failures}"
        )

    def test_accepted_payment_terms(self, bronze_suppliers):
        """SUP999 ghost record has blank payment_terms — allow max 1 violation."""
        result = ConsistencyValidator(bronze_suppliers, "bronze_suppliers").check_accepted_values(
            "payment_terms", ACCEPTED_PAYMENT_TERMS
        )
        max_allowed = 1  # SUP999 from decommissioned legacy system (JIRA: DQ-145)
        assert len(result.failures) <= max_allowed, (
            f"Payment terms violations grew beyond accepted {max_allowed}: "
            f"{len(result.failures)} found.\nBad values: {result.failures}"
        )

    def test_quality_rating_in_range(self, bronze_suppliers):
        result = ConsistencyValidator(bronze_suppliers, "bronze_suppliers").check_numeric_range(
            "quality_rating", min_val=1.0, max_val=5.0
        )
        assert result.passed, f"{result.summary}\nOut-of-range: {result.failures}"

    def test_contract_date_iso_format(self, bronze_suppliers):
        """Bronze may have dates in DD/MM/YYYY format — this test documents the known issue."""
        result = ConsistencyValidator(bronze_suppliers, "bronze_suppliers").check_date_format(
            "contract_start_date", fmt="%Y-%m-%d"
        )
        # We assert the known count of malformed dates doesn't grow beyond what was triage'd
        # SUP004 has DD/MM/YYYY; SUP999 ghost record has '-999' — 2 known violations
        max_allowed_failures = 2
        assert len(result.failures) <= max_allowed_failures, (
            f"Date format violations grew beyond accepted {max_allowed_failures}: "
            f"{len(result.failures)} found.\nDetails: {result.failures}"
        )

    def test_email_format_when_present(self, bronze_suppliers):
        """Non-null emails must be valid format."""
        result = ConsistencyValidator(bronze_suppliers, "bronze_suppliers").check_email_format(
            "email"
        )
        assert result.passed, f"{result.summary}\nBad emails: {result.failures}"

    def test_supplier_name_no_leading_trailing_whitespace(self, bronze_suppliers):
        """Raw feed from ERP_SAP has known whitespace padding on supplier names."""
        result = CompletenessValidator(
            bronze_suppliers, "bronze_suppliers"
        ).check_no_leading_trailing_whitespace(["supplier_name"])
        # Document known issue: SUP003 has ' Parker Hannifin ' — must not grow
        max_allowed = 1
        assert len(result.failures) <= max_allowed, (
            f"Whitespace violations grew beyond accepted {max_allowed}: "
            f"{len(result.failures)} found.\nDetails: {result.failures}"
        )
