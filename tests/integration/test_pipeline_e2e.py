"""
End-to-end pipeline validation.

Tests the full Bronze → Silver → Gold data flow:
  - Row count SLA at each layer transition
  - No phantom records introduced during transformation
  - Spend figures reconcile from Silver work orders to Gold metrics
  - Critical parts never silently dropped
"""
import pytest
import pandas as pd

from src.validators.reconciliation_validator import ReconciliationValidator

pytestmark = pytest.mark.integration


class TestBronzeToSilverPipeline:

    def test_row_count_slas(
        self,
        bronze_suppliers, silver_suppliers,
        bronze_parts, silver_parts,
        bronze_work_orders, silver_work_orders,
    ):
        """Silver must retain the agreed minimum percentage of rows from each bronze table."""
        checks = [
            (bronze_suppliers, silver_suppliers, "suppliers", 10.0),
            (bronze_parts,     silver_parts,     "parts",     15.0),
            (bronze_work_orders, silver_work_orders, "work_orders", 6.0),
        ]
        failures = []
        for bronze_df, silver_df, entity, max_drop in checks:
            result = ReconciliationValidator(
                bronze_df, silver_df, f"bronze_{entity}", f"silver_{entity}"
            ).check_row_count_delta(max_drop_pct=max_drop, max_gain_pct=0.0)
            if not result.passed:
                failures.append(f"{entity} SLA breach — {result.summary}")
        assert len(failures) == 0, (
            "Row count SLA failures detected:\n" + "\n".join(failures) + "\n"
            "Investigate cleansing pipeline for over-aggressive filtering."
        )

    def test_no_phantom_pks_in_silver(
        self,
        bronze_suppliers, silver_suppliers,
        bronze_parts, silver_parts,
        bronze_work_orders, silver_work_orders,
    ):
        """Silver must not introduce primary keys that do not exist in the bronze source."""
        checks = [
            (bronze_suppliers,   silver_suppliers,   "supplier_id"),
            (bronze_parts,       silver_parts,       "part_id"),
            (bronze_work_orders, silver_work_orders, "work_order_id"),
        ]
        failures = []
        for bronze_df, silver_df, pk_col in checks:
            result = ReconciliationValidator(
                bronze_df, silver_df, "bronze", "silver"
            ).check_no_new_pks(pk_col)
            if not result.passed:
                failures.append(f"[{pk_col}] {result.summary}  phantoms={result.failures}")
        assert len(failures) == 0, (
            "Phantom PKs detected in silver layer:\n" + "\n".join(failures) + "\n"
            "Silver transformation must not inject records absent from bronze."
        )


class TestSilverToGoldPipeline:

    def test_gold_spend_sourced_from_silver_closed_orders(
        self, silver_work_orders, silver_parts, gold_metrics
    ):
        """Gold total_spend must reconcile to Silver work order totals for overlapping months.

        Compares spend only for (metric_month, supplier_id) combinations present in Gold —
        Gold may be a partial window (e.g. Q1 only) while Silver covers a longer period.
        """
        closed_silver = silver_work_orders[
            silver_work_orders["status"].isin(["CLOSED", "PARTIAL"])
        ].copy()
        closed_silver["metric_month"] = pd.to_datetime(
            closed_silver["order_date"], errors="coerce"
        ).dt.strftime("%Y-%m")

        gold_months = set(gold_metrics["metric_month"].astype(str).unique())
        gold_suppliers = set(gold_metrics["supplier_id"].astype(str).unique())

        if not gold_months:
            pytest.skip("Gold metrics table is empty")

        silver_with_sup = closed_silver.merge(
            silver_parts[["part_id", "supplier_id"]], on="part_id", how="inner"
        )
        silver_scoped = silver_with_sup[
            silver_with_sup["metric_month"].isin(gold_months)
            & silver_with_sup["supplier_id"].astype(str).isin(gold_suppliers)
        ]
        silver_total = silver_scoped["total_cost"].astype(float).sum()
        gold_total = gold_metrics["total_spend"].astype(float).sum()

        tolerance_pct = 10.0
        if silver_total > 0:
            diff_pct = abs(silver_total - gold_total) / silver_total * 100
            assert diff_pct <= tolerance_pct, (
                f"Scoped Silver total_cost ({silver_total:,.2f}) vs Gold total_spend "
                f"({gold_total:,.2f}) differ by {diff_pct:.2f}% (threshold: {tolerance_pct}%).\n"
                "Investigate Gold aggregation logic — possible missing or double-counted records."
            )

    def test_all_silver_suppliers_with_orders_have_gold_metrics(
        self, silver_work_orders, silver_parts, gold_metrics
    ):
        """Suppliers that placed closed orders in months covered by Gold must appear in Gold."""
        closed = silver_work_orders[
            silver_work_orders["status"].isin(["CLOSED", "PARTIAL"])
        ].copy()
        closed["metric_month"] = pd.to_datetime(
            closed["order_date"], errors="coerce"
        ).dt.strftime("%Y-%m")

        gold_months = set(gold_metrics["metric_month"].astype(str).unique())

        in_scope = closed[closed["metric_month"].isin(gold_months)].merge(
            silver_parts[["part_id", "supplier_id"]], on="part_id", how="inner"
        )
        expected_in_gold = set(in_scope["supplier_id"].astype(str).unique())
        gold_suppliers = set(gold_metrics["supplier_id"].astype(str).unique())
        missing = expected_in_gold - gold_suppliers
        assert len(missing) == 0, (
            f"Suppliers with closed orders in Gold months but absent from Gold: {sorted(missing)}\n"
            "Gold aggregation must include all suppliers with activity in the reporting window."
        )

    def test_gold_defect_counts_non_negative(self, gold_metrics):
        invalid = gold_metrics[gold_metrics["defect_count"] < 0]
        assert len(invalid) == 0, (
            f"{len(invalid)} Gold rows with negative defect_count:\n"
            f"{invalid[['metric_month', 'supplier_id', 'defect_count']]}"
        )

    def test_gold_month_continuity(self, gold_metrics):
        """Gold should have contiguous monthly data — no silent gaps > 1 month."""
        months = (
            pd.to_datetime(gold_metrics["metric_month"], format="%Y-%m")
            .sort_values()
            .unique()
        )
        if len(months) < 2:
            pytest.skip("Not enough months to check continuity")
        gaps = []
        for i in range(1, len(months)):
            diff_months = (months[i].year - months[i - 1].year) * 12 + (
                months[i].month - months[i - 1].month
            )
            if diff_months > 1:
                gaps.append(
                    f"Gap between {months[i-1].strftime('%Y-%m')} and {months[i].strftime('%Y-%m')}"
                )
        assert len(gaps) == 0, (
            "Month continuity gaps detected in Gold layer:\n" + "\n".join(gaps)
        )


class TestFullPipelineDataLineage:

    def test_every_gold_supplier_traceable_to_bronze(
        self, bronze_suppliers, gold_metrics
    ):
        """Gold supplier_ids must trace back to bronze source."""
        bronze_ids = set(bronze_suppliers["supplier_id"].astype(str).dropna().unique())
        gold_ids = set(gold_metrics["supplier_id"].astype(str).unique())
        untraceable = gold_ids - bronze_ids
        assert len(untraceable) == 0, (
            f"Gold supplier_ids not traceable to bronze: {sorted(untraceable)}\n"
            "Violates data lineage — possible injection of unaudited records."
        )

    def test_work_order_part_ids_traceable_to_bronze_parts(
        self, bronze_work_orders, bronze_parts
    ):
        """All bronze work order part_ids (excluding known orphan PARTXXX) should be in parts."""
        known_orphans = {"PARTXXX"}
        wo_part_ids = set(
            bronze_work_orders["part_id"].astype(str).dropna().unique()
        ) - known_orphans
        part_ids = set(bronze_parts["part_id"].astype(str).unique())
        untraceable = wo_part_ids - part_ids
        assert len(untraceable) == 0, (
            f"Work order part_ids not in parts catalog: {sorted(untraceable)}\n"
            "Raise DQ ticket to validate source system referential integrity."
        )
