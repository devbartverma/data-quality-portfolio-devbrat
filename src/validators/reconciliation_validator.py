"""Reconciliation validation: row counts, aggregation totals, cross-layer consistency."""
from __future__ import annotations

from typing import Optional

import pandas as pd

from .completeness_validator import ValidationResult


class ReconciliationValidator:
    """Validates data consistency across pipeline layers (Bronze→Silver→Gold)."""

    def __init__(
        self,
        source_df: pd.DataFrame,
        target_df: pd.DataFrame,
        source_name: str = "source",
        target_name: str = "target",
    ):
        self.source = source_df
        self.target = target_df
        self.source_name = source_name
        self.target_name = target_name

    # ------------------------------------------------------------------
    # Public checks
    # ------------------------------------------------------------------

    def check_row_count_delta(
        self,
        max_drop_pct: float = 5.0,
        max_gain_pct: float = 0.0,
    ) -> ValidationResult:
        """Fail if row count change between source and target exceeds thresholds.

        A drop is expected (dirty rows removed); a gain is suspicious.
        """
        src_count = len(self.source)
        tgt_count = len(self.target)
        if src_count == 0:
            return ValidationResult(
                rule="row_count_delta_check",
                passed=False,
                failures=[{"error": "Source DataFrame is empty"}],
                summary="Source is empty — cannot compare",
            )
        drop_pct = max(0.0, (src_count - tgt_count) / src_count * 100)
        gain_pct = max(0.0, (tgt_count - src_count) / src_count * 100)
        over_drop = drop_pct > max_drop_pct
        over_gain = gain_pct > max_gain_pct
        passed = not over_drop and not over_gain
        failures = (
            []
            if passed
            else [
                {
                    "source_rows": src_count,
                    "target_rows": tgt_count,
                    "drop_pct": round(drop_pct, 2),
                    "gain_pct": round(gain_pct, 2),
                    "max_drop_pct": max_drop_pct,
                    "max_gain_pct": max_gain_pct,
                }
            ]
        )
        summary = (
            f"{self.source_name}={src_count} → {self.target_name}={tgt_count} "
            f"(drop={drop_pct:.1f}%, gain={gain_pct:.1f}%)"
        )
        return ValidationResult(
            rule="row_count_delta_check", passed=passed, failures=failures, summary=summary
        )

    def check_no_new_pks(
        self, pk_column: str
    ) -> ValidationResult:
        """Fail if the target contains PK values that don't exist in source.

        Detects phantom rows injected between layers.
        """
        src_keys = set(self.source[pk_column].dropna().astype(str).unique())
        tgt_keys = set(self.target[pk_column].dropna().astype(str).unique())
        new_keys = tgt_keys - src_keys
        passed = len(new_keys) == 0
        failures = [{"pk_value": k} for k in sorted(new_keys)]
        summary = (
            f"No new '{pk_column}' values in {self.target_name}"
            if passed
            else f"{len(new_keys)} PK(s) in {self.target_name} not found in {self.source_name}"
        )
        return ValidationResult(
            rule="no_new_pks_check", passed=passed, failures=failures, summary=summary
        )

    def check_numeric_sum_match(
        self,
        column: str,
        tolerance_pct: float = 0.01,
        source_filter: Optional[pd.Series] = None,
        target_filter: Optional[pd.Series] = None,
    ) -> ValidationResult:
        """Fail if the column sum differs between source and target beyond *tolerance_pct*.

        Used to verify aggregation fidelity (e.g. Silver total_cost == Gold total_spend).
        """
        src = self.source if source_filter is None else self.source[source_filter]
        tgt = self.target if target_filter is None else self.target[target_filter]

        src_sum = pd.to_numeric(src[column], errors="coerce").sum()
        tgt_sum = pd.to_numeric(tgt[column], errors="coerce").sum()

        if src_sum == 0 and tgt_sum == 0:
            return ValidationResult(
                rule="numeric_sum_match_check",
                passed=True,
                failures=[],
                summary=f"Both sums for '{column}' are 0 — trivially matched",
            )

        abs_diff = abs(src_sum - tgt_sum)
        diff_pct = abs_diff / abs(src_sum) * 100 if src_sum != 0 else float("inf")
        passed = diff_pct <= tolerance_pct
        failures = (
            []
            if passed
            else [
                {
                    "column": column,
                    "source_sum": round(float(src_sum), 2),
                    "target_sum": round(float(tgt_sum), 2),
                    "diff_pct": round(diff_pct, 4),
                    "tolerance_pct": tolerance_pct,
                }
            ]
        )
        summary = (
            f"'{column}' sums match: {src_sum:.2f} ≈ {tgt_sum:.2f} (diff={diff_pct:.4f}%)"
            if passed
            else f"'{column}' sum mismatch: {src_sum:.2f} vs {tgt_sum:.2f} ({diff_pct:.2f}% diff)"
        )
        return ValidationResult(
            rule="numeric_sum_match_check", passed=passed, failures=failures, summary=summary
        )

    def check_no_dropped_critical_rows(
        self,
        pk_column: str,
        critical_filter_column: str,
        critical_value,
    ) -> ValidationResult:
        """Fail if any rows flagged as critical in source are absent from target."""
        critical_src = self.source[
            self.source[critical_filter_column] == critical_value
        ][pk_column].astype(str)
        tgt_keys = set(self.target[pk_column].astype(str).unique())
        dropped = critical_src[~critical_src.isin(tgt_keys)]
        passed = len(dropped) == 0
        failures = [{"pk_value": v} for v in sorted(dropped.unique())]
        summary = (
            f"All critical rows ('{critical_filter_column}'=={critical_value!r}) "
            f"retained in {self.target_name}"
            if passed
            else f"{len(dropped)} critical row(s) dropped from {self.target_name}"
        )
        return ValidationResult(
            rule="no_dropped_critical_rows_check",
            passed=passed,
            failures=failures,
            summary=summary,
        )
