"""Silver layer SQL validation — hard gate, every query must return zero violations.

Mirrors sql/silver/01_referential_integrity.sql and sql/silver/02_business_rules.sql
but runs live in CI against the cleansed CSVs via DuckDB.

Any failure here means the cleansing pipeline did not resolve a known Bronze defect
and the Gold aggregation job must not proceed.
"""
import pytest

pytestmark = pytest.mark.sql


class TestSilverSuppliersSQL:
    """Referential integrity and business rules on suppliers_cleansed."""

    def test_no_null_supplier_id(self, duckdb_con):
        count = duckdb_con.execute(
            "SELECT COUNT(*) FROM silver_suppliers WHERE supplier_id IS NULL"
        ).fetchone()[0]
        assert count == 0, f"supplier_id has {count} NULL(s) in silver — pipeline must guarantee PK"

    def test_no_null_email(self, duckdb_con):
        """SUP006 and SUP999 must be resolved or excluded before Silver promotion."""
        count = duckdb_con.execute(
            "SELECT COUNT(*) FROM silver_suppliers WHERE email IS NULL OR TRIM(email) = ''"
        ).fetchone()[0]
        assert count == 0, f"{count} null/blank email(s) in silver — all emails must be populated"

    def test_no_null_supplier_name(self, duckdb_con):
        count = duckdb_con.execute(
            "SELECT COUNT(*) FROM silver_suppliers WHERE supplier_name IS NULL OR TRIM(supplier_name) = ''"
        ).fetchone()[0]
        assert count == 0, f"{count} null/blank supplier_name(s) in silver"

    def test_supplier_pk_unique(self, duckdb_con):
        dupes = duckdb_con.execute(
            """
            SELECT supplier_id, COUNT(*) AS cnt
            FROM silver_suppliers
            GROUP BY supplier_id
            HAVING COUNT(*) > 1
            """
        ).fetchall()
        assert len(dupes) == 0, f"Duplicate supplier_ids in silver: {dupes}"

    def test_no_whitespace_in_supplier_name(self, duckdb_con):
        """SUP003 leading whitespace must be stripped by the cleansing pipeline."""
        count = duckdb_con.execute(
            "SELECT COUNT(*) FROM silver_suppliers WHERE supplier_name != TRIM(supplier_name)"
        ).fetchone()[0]
        assert count == 0, f"{count} supplier_name(s) have leading/trailing whitespace in silver"

    def test_no_invalid_status(self, duckdb_con):
        """SUP999 (LEGACY_SYSTEM) must be excluded — only governed status values allowed."""
        rows = duckdb_con.execute(
            """
            SELECT status, COUNT(*) AS cnt
            FROM silver_suppliers
            WHERE status NOT IN ('ACTIVE', 'INACTIVE', 'PROBATION', 'SUSPENDED')
            GROUP BY status
            """
        ).fetchall()
        assert len(rows) == 0, f"Invalid status values in silver: {rows}"

    def test_no_invalid_payment_terms(self, duckdb_con):
        rows = duckdb_con.execute(
            """
            SELECT payment_terms, COUNT(*) AS cnt
            FROM silver_suppliers
            WHERE payment_terms NOT IN ('NET30', 'NET45', 'NET60', 'NET90')
            GROUP BY payment_terms
            """
        ).fetchall()
        assert len(rows) == 0, f"Invalid payment_terms in silver: {rows}"

    def test_quality_rating_in_range(self, duckdb_con):
        count = duckdb_con.execute(
            """
            SELECT COUNT(*) FROM silver_suppliers
            WHERE CAST(quality_rating AS DOUBLE) < 1.0
               OR CAST(quality_rating AS DOUBLE) > 5.0
            """
        ).fetchone()[0]
        assert count == 0, f"{count} supplier(s) have quality_rating outside 1.0–5.0 in silver"

    def test_all_iso_contract_dates(self, duckdb_con):
        """SUP004 (DD/MM/YYYY) and SUP999 (-999) must be corrected or excluded before Silver."""
        count = duckdb_con.execute(
            """
            SELECT COUNT(*) FROM silver_suppliers
            WHERE TRY_STRPTIME(CAST(contract_start_date AS VARCHAR), '%Y-%m-%d') IS NULL
              AND contract_start_date IS NOT NULL
            """
        ).fetchone()[0]
        assert count == 0, f"{count} non-ISO contract_start_date values remain in silver"


class TestSilverPartsSQL:
    """Business rules and FK integrity on parts_catalog_cleansed."""

    def test_part_pk_unique(self, duckdb_con):
        dupes = duckdb_con.execute(
            """
            SELECT part_id, COUNT(*) AS cnt
            FROM silver_parts
            GROUP BY part_id
            HAVING COUNT(*) > 1
            """
        ).fetchall()
        assert len(dupes) == 0, f"Duplicate part_ids in silver: {dupes}"

    def test_no_negative_unit_price(self, duckdb_con):
        """PART026 (-$500) must be excluded from Silver."""
        count = duckdb_con.execute(
            "SELECT COUNT(*) FROM silver_parts WHERE CAST(unit_price AS DOUBLE) <= 0"
        ).fetchone()[0]
        assert count == 0, (
            f"{count} parts with non-positive unit_price in silver.\n"
            "PART026 must be excluded by the cleansing pipeline before Silver promotion."
        )

    def test_no_null_part_name(self, duckdb_con):
        """PART028 (blank from ERP truncation) must be resolved before Silver."""
        count = duckdb_con.execute(
            "SELECT COUNT(*) FROM silver_parts WHERE part_name IS NULL OR TRIM(part_name) = ''"
        ).fetchone()[0]
        assert count == 0, (
            f"{count} null/blank part_name(s) in silver.\n"
            "PART028 ERP truncation defect must be resolved or the record excluded."
        )

    def test_parts_supplier_fk_integrity(self, duckdb_con):
        """Every part's supplier_id must exist in silver_suppliers.

        PART027 (null) and PART030 (SUPXXX orphan) must be resolved or excluded.
        Failure here means Silver parts reference a non-existent supplier.
        """
        orphans = duckdb_con.execute(
            """
            SELECT p.part_id, p.supplier_id
            FROM silver_parts p
            LEFT JOIN silver_suppliers s ON p.supplier_id = s.supplier_id
            WHERE p.supplier_id IS NOT NULL
              AND s.supplier_id IS NULL
            ORDER BY p.part_id
            """
        ).fetchall()
        assert len(orphans) == 0, (
            f"Orphaned supplier references in silver_parts: {orphans}\n"
            "PART030 (SUPXXX) must be excluded or corrected before Silver promotion."
        )


class TestSilverWorkOrdersSQL:
    """Business rules on work_orders_cleansed."""

    def test_work_order_pk_unique(self, duckdb_con):
        dupes = duckdb_con.execute(
            """
            SELECT work_order_id, COUNT(*) AS cnt
            FROM silver_work_orders
            GROUP BY work_order_id
            HAVING COUNT(*) > 1
            """
        ).fetchall()
        assert len(dupes) == 0, f"Duplicate work_order_ids in silver: {dupes}"

    def test_no_closed_orders_missing_delivery(self, duckdb_con):
        """WO-2024-050 (CLOSED with null delivery) must be resolved or excluded before Silver."""
        count = duckdb_con.execute(
            """
            SELECT COUNT(*) FROM silver_work_orders
            WHERE status = 'CLOSED' AND actual_delivery IS NULL
            """
        ).fetchone()[0]
        assert count == 0, (
            f"{count} CLOSED work order(s) have null actual_delivery in silver.\n"
            "WO-2024-050 must be corrected or excluded by the cleansing pipeline."
        )

    def test_no_invalid_work_order_status(self, duckdb_con):
        rows = duckdb_con.execute(
            """
            SELECT status, COUNT(*) AS cnt
            FROM silver_work_orders
            WHERE status NOT IN ('OPEN', 'CLOSED', 'PARTIAL', 'CANCELLED')
            GROUP BY status
            """
        ).fetchall()
        assert len(rows) == 0, f"Invalid work order status values in silver: {rows}"
