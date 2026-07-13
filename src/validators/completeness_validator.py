"""Completeness validation: nulls, row counts, required columns, empty strings."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import pandas as pd


@dataclass
class ValidationResult:
    rule: str
    passed: bool
    failures: list[dict] = field(default_factory=list)
    summary: str = ""

    def __str__(self) -> str:  # pragma: no cover
        status = "PASS" if self.passed else "FAIL"
        return f"[{status}] {self.rule}: {self.summary}"


class CompletenessValidator:
    """Validates data completeness of a pandas DataFrame."""

    def __init__(self, df: pd.DataFrame, table_name: str = "unknown"):
        self.df = df
        self.table_name = table_name

    # ------------------------------------------------------------------
    # Public checks
    # ------------------------------------------------------------------

    def check_null_rates(
        self,
        columns: Optional[list[str]] = None,
        threshold: float = 0.05,
    ) -> ValidationResult:
        """Fail if any column's null rate exceeds *threshold* (default 5 %)."""
        cols = columns or list(self.df.columns)
        total = len(self.df)
        failures = []
        for col in cols:
            null_count = int(self.df[col].isna().sum())
            rate = null_count / total if total > 0 else 0.0
            if rate > threshold:
                failures.append(
                    {
                        "column": col,
                        "null_count": null_count,
                        "null_rate_pct": round(rate * 100, 2),
                        "threshold_pct": round(threshold * 100, 2),
                    }
                )

        passed = len(failures) == 0
        summary = (
            f"All {len(cols)} columns within {threshold*100:.0f}% null threshold"
            if passed
            else f"{len(failures)} column(s) exceed null threshold"
        )
        return ValidationResult(
            rule="null_rate_check",
            passed=passed,
            failures=failures,
            summary=summary,
        )

    def check_required_columns(self, required: list[str]) -> ValidationResult:
        """Fail if any *required* column is missing from the DataFrame."""
        missing = [c for c in required if c not in self.df.columns]
        passed = len(missing) == 0
        return ValidationResult(
            rule="required_columns_check",
            passed=passed,
            failures=[{"missing_column": c} for c in missing],
            summary=(
                f"All {len(required)} required columns present"
                if passed
                else f"Missing columns: {missing}"
            ),
        )

    def check_row_count(
        self,
        min_rows: int,
        max_rows: Optional[int] = None,
    ) -> ValidationResult:
        """Fail if row count is outside [*min_rows*, *max_rows*]."""
        actual = len(self.df)
        too_low = actual < min_rows
        too_high = max_rows is not None and actual > max_rows
        passed = not too_low and not too_high
        failures = []
        if not passed:
            failures.append(
                {
                    "actual_row_count": actual,
                    "min_rows": min_rows,
                    "max_rows": max_rows,
                }
            )
        summary = (
            f"Row count {actual} within expected range [{min_rows}, {max_rows or '∞'}]"
            if passed
            else f"Row count {actual} outside expected range [{min_rows}, {max_rows or '∞'}]"
        )
        return ValidationResult(
            rule="row_count_check", passed=passed, failures=failures, summary=summary
        )

    def check_no_empty_strings(self, columns: list[str]) -> ValidationResult:
        """Fail if any cell in *columns* is an empty string or whitespace-only."""
        failures = []
        for col in columns:
            if col not in self.df.columns:
                continue
            mask = self.df[col].astype(str).str.strip() == ""
            empty_rows = self.df[mask]
            for idx, row in empty_rows.iterrows():
                failures.append({"column": col, "row_index": int(idx)})

        passed = len(failures) == 0
        summary = (
            f"No empty strings found in {len(columns)} column(s)"
            if passed
            else f"{len(failures)} empty string(s) found"
        )
        return ValidationResult(
            rule="no_empty_strings_check", passed=passed, failures=failures, summary=summary
        )

    def check_no_leading_trailing_whitespace(self, columns: list[str]) -> ValidationResult:
        """Fail if any string column has leading/trailing whitespace."""
        failures = []
        for col in columns:
            if col not in self.df.columns:
                continue
            str_col = self.df[col].dropna().astype(str)
            mask = str_col != str_col.str.strip()
            for idx in str_col[mask].index:
                failures.append(
                    {"column": col, "row_index": int(idx), "value": repr(self.df.loc[idx, col])}
                )

        passed = len(failures) == 0
        summary = (
            f"No whitespace padding in {len(columns)} column(s)"
            if passed
            else f"{len(failures)} cell(s) have leading/trailing whitespace"
        )
        return ValidationResult(
            rule="no_whitespace_padding_check", passed=passed, failures=failures, summary=summary
        )

    def check_pk_uniqueness(self, pk_column: str) -> ValidationResult:
        """Fail if *pk_column* contains duplicate values."""
        if pk_column not in self.df.columns:
            return ValidationResult(
                rule="pk_uniqueness_check",
                passed=False,
                failures=[{"error": f"Column '{pk_column}' not found"}],
                summary=f"Column '{pk_column}' not found",
            )
        dupes = self.df[self.df.duplicated(subset=[pk_column], keep=False)]
        passed = len(dupes) == 0
        failures = dupes[[pk_column]].drop_duplicates().to_dict("records") if not passed else []
        summary = (
            f"No duplicate values in '{pk_column}'"
            if passed
            else f"{len(dupes)} rows with duplicate '{pk_column}' values"
        )
        return ValidationResult(
            rule="pk_uniqueness_check", passed=passed, failures=failures, summary=summary
        )
