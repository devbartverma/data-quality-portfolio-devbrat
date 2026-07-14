"""Bronze layer SQL validation — executed via DuckDB against the raw CSVs.

Mirrors the checks in sql/bronze/01_completeness_checks.sql and
sql/bronze/02_format_validation.sql but runs live in CI with no database server.

Bronze rules allow documented violations up to a JIRA-tracked maximum.
Exceeding the threshold fails CI and triggers a new remediation task.
"""
import pytest

pytestmark = pytest.mark.sql


class TestBronzeSuppliersSQL:
    """Completeness and format checks on suppliers_raw — mirrors sql/bronze/."""

    def test_supplier_id_never_null(self, duckdb_con):
        """PK column — zero null tolerance regardless of source system issues."""
        count = duckdb_con.execute(
            "SELECT COUNT(*) FROM bronze_suppliers WHERE supplier_id IS NULL"
        ).fetchone()[0]
        assert count == 0, f"supplier_id has {count} NULL(s) — PK cannot be null"

    def test_email_null_rate_within_threshold(self, duckdb_con):
        """Email null rate ≤ 15% (SUP006: missing contact · SUP999: ghost record — DQ-141, DQ-145)."""
        total, nulls = duckdb_con.execute(
            """
            SELECT
                COUNT(*),
                SUM(CASE WHEN email IS NULL OR TRIM(email) = '' THEN 1 ELSE 0 END)
            FROM bronze_suppliers
            """
        ).fetchone()
        rate = (nulls / total) * 100
        assert rate <= 15.0, (
            f"Email null rate {rate:.1f}% exceeds 15% threshold ({nulls}/{total} rows).\n"
            "Growth beyond 2 null emails indicates new source-side data loss."
        )

    def test_accepted_status_values_max_one_violation(self, duckdb_con):
        """Status must be in approved set — max 1 rogue value (SUP999: LEGACY_SYSTEM — DQ-145)."""
        count = duckdb_con.execute(
            """
            SELECT COUNT(*) FROM bronze_suppliers
            WHERE status NOT IN ('ACTIVE', 'INACTIVE', 'PROBATION', 'SUSPENDED')
            """
        ).fetchone()[0]
        assert count <= 1, (
            f"{count} rows have an invalid status (threshold: 1).\n"
            "SUP999 (LEGACY_SYSTEM) is documented. A count > 1 means a new rogue record — raise DQ ticket."
        )

    def test_contract_date_format_violations_within_threshold(self, duckdb_con):
        """Non-ISO dates ≤ 2 (SUP004: DD/MM/YYYY · SUP999: -999 sentinel — DQ-133, DQ-145)."""
        count = duckdb_con.execute(
            """
            SELECT COUNT(*) FROM bronze_suppliers
            WHERE TRY_STRPTIME(CAST(contract_start_date AS VARCHAR), '%Y-%m-%d') IS NULL
              AND contract_start_date IS NOT NULL
              AND TRIM(CAST(contract_start_date AS VARCHAR)) != ''
            """
        ).fetchone()[0]
        assert count <= 2, (
            f"{count} contract_start_date values cannot be parsed as YYYY-MM-DD (threshold: 2).\n"
            "SUP004 (DD/MM/YYYY) and SUP999 (-999) are known. New violations require source-side triage."
        )

    def test_whitespace_in_supplier_name_within_threshold(self, duckdb_con):
        """Whitespace padding ≤ 1 row (SUP003: leading space from ERP extract — DQ-130)."""
        count = duckdb_con.execute(
            "SELECT COUNT(*) FROM bronze_suppliers WHERE supplier_name != TRIM(supplier_name)"
        ).fetchone()[0]
        assert count <= 1, (
            f"{count} supplier_name(s) have leading/trailing whitespace (threshold: 1).\n"
            "SUP003 is the documented ERP extract defect. New padded names need investigation."
        )

    def test_quality_rating_in_range(self, duckdb_con):
        """Numeric quality_rating values must be 1.0–5.0 (non-numeric values are separate violations).

        SUP999 carries 'INACTIVE' in this column due to a missing field in the source CSV row —
        TRY_CAST coerces it to NULL so only numeric values are range-checked.
        """
        count = duckdb_con.execute(
            """
            SELECT COUNT(*) FROM bronze_suppliers
            WHERE TRY_CAST(quality_rating AS DOUBLE) IS NOT NULL
              AND (TRY_CAST(quality_rating AS DOUBLE) < 1.0
                   OR TRY_CAST(quality_rating AS DOUBLE) > 5.0)
            """
        ).fetchone()[0]
        assert count == 0, f"{count} supplier(s) have numeric quality_rating outside 1.0–5.0"


class TestBronzePartsSQL:
    """Completeness and range checks on parts_catalog_raw — mirrors sql/bronze/."""

    def test_part_pk_never_null(self, duckdb_con):
        """part_id is the PK — zero null tolerance."""
        count = duckdb_con.execute(
            "SELECT COUNT(*) FROM bronze_parts WHERE part_id IS NULL"
        ).fetchone()[0]
        assert count == 0, f"part_id has {count} NULL(s) — PK cannot be null"

    def test_negative_unit_price_within_threshold(self, duckdb_con):
        """Negative price ≤ 1 row (PART026: -$500 from legacy migration — DQ-137)."""
        count = duckdb_con.execute(
            "SELECT COUNT(*) FROM bronze_parts WHERE CAST(unit_price AS DOUBLE) < 0"
        ).fetchone()[0]
        assert count <= 1, (
            f"{count} parts have a negative unit_price (threshold: 1).\n"
            "PART026 (-$500) is the documented legacy migration defect. New negative prices need urgent triage."
        )

    def test_null_part_name_within_threshold(self, duckdb_con):
        """Null/blank part_name ≤ 1 row (PART028: ERP truncation bug — DQ-142)."""
        count = duckdb_con.execute(
            "SELECT COUNT(*) FROM bronze_parts WHERE part_name IS NULL OR TRIM(part_name) = ''"
        ).fetchone()[0]
        assert count <= 1, (
            f"{count} parts have a null/blank part_name (threshold: 1).\n"
            "PART028 is the documented ERP extract truncation. Review if count grows."
        )

    def test_null_supplier_id_within_threshold(self, duckdb_con):
        """Null supplier_id ≤ 1 row (PART027: MDM onboarding pending — DQ-155)."""
        count = duckdb_con.execute(
            "SELECT COUNT(*) FROM bronze_parts WHERE supplier_id IS NULL"
        ).fetchone()[0]
        assert count <= 1, (
            f"{count} parts have a null supplier_id (threshold: 1).\n"
            "PART027 is pending MDM onboarding. Growth beyond 1 triggers escalation."
        )

    def test_lead_time_days_positive(self, duckdb_con):
        """All lead times must be 1–365 days — business rule, no tolerance."""
        count = duckdb_con.execute(
            "SELECT COUNT(*) FROM bronze_parts WHERE lead_time_days < 1 OR lead_time_days > 365"
        ).fetchone()[0]
        assert count == 0, f"{count} part(s) have lead_time_days outside 1–365"


class TestBronzeWorkOrdersSQL:
    """Completeness and status checks on work_orders_raw — mirrors sql/bronze/."""

    def test_work_order_pk_never_null(self, duckdb_con):
        """work_order_id is the PK — zero null tolerance."""
        count = duckdb_con.execute(
            "SELECT COUNT(*) FROM bronze_work_orders WHERE work_order_id IS NULL"
        ).fetchone()[0]
        assert count == 0, f"work_order_id has {count} NULL(s) — PK cannot be null"

    def test_closed_null_delivery_within_threshold(self, duckdb_con):
        """CLOSED orders with null actual_delivery ≤ 1 (WO-2024-050 known — DQ-165)."""
        count = duckdb_con.execute(
            """
            SELECT COUNT(*) FROM bronze_work_orders
            WHERE status = 'CLOSED' AND actual_delivery IS NULL
            """
        ).fetchone()[0]
        assert count <= 1, (
            f"{count} CLOSED work order(s) have null actual_delivery (threshold: 1).\n"
            "WO-2024-050 is documented. Growth beyond 1 requires immediate DQ investigation."
        )

    def test_accepted_work_order_status(self, duckdb_con):
        """Status must be OPEN / CLOSED / PARTIAL / CANCELLED — zero rogue values tolerated."""
        rows = duckdb_con.execute(
            """
            SELECT status, COUNT(*) AS cnt FROM bronze_work_orders
            WHERE status NOT IN ('OPEN', 'CLOSED', 'PARTIAL', 'CANCELLED')
            GROUP BY status
            ORDER BY cnt DESC
            """
        ).fetchall()
        assert len(rows) == 0, (
            f"Unexpected status values found: {rows}\n"
            "Rogue status from source system — raise DQ ticket for source-side fix."
        )
