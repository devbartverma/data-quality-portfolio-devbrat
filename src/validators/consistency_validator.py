"""Consistency validation: accepted values, numeric ranges, date formats, FK integrity."""
from __future__ import annotations

import re
from typing import Optional, Union

import pandas as pd

from .completeness_validator import ValidationResult


class ConsistencyValidator:
    """Validates business rules and referential consistency of a DataFrame."""

    def __init__(self, df: pd.DataFrame, table_name: str = "unknown"):
        self.df = df
        self.table_name = table_name

    # ------------------------------------------------------------------
    # Public checks
    # ------------------------------------------------------------------

    def check_accepted_values(
        self, column: str, accepted: list
    ) -> ValidationResult:
        """Fail if *column* contains values outside the *accepted* set."""
        if column not in self.df.columns:
            return self._column_missing(column, "accepted_values_check")
        mask = ~self.df[column].isin(accepted)
        bad_rows = self.df[mask]
        passed = len(bad_rows) == 0
        failures = (
            bad_rows[[column]].value_counts().reset_index().rename(
                columns={column: "value", 0: "count"}
            ).to_dict("records")
            if not passed
            else []
        )
        summary = (
            f"All values in '{column}' are within accepted set"
            if passed
            else f"{len(bad_rows)} row(s) in '{column}' have non-accepted values"
        )
        return ValidationResult(
            rule="accepted_values_check", passed=passed, failures=failures, summary=summary
        )

    def check_numeric_range(
        self,
        column: str,
        min_val: Optional[float] = None,
        max_val: Optional[float] = None,
        allow_null: bool = True,
    ) -> ValidationResult:
        """Fail if *column* numeric values are outside [*min_val*, *max_val*]."""
        if column not in self.df.columns:
            return self._column_missing(column, "numeric_range_check")
        series = pd.to_numeric(self.df[column], errors="coerce")
        if not allow_null:
            null_mask = series.isna()
        else:
            null_mask = pd.Series([False] * len(series), index=series.index)

        out_of_range = pd.Series([False] * len(series), index=series.index)
        if min_val is not None:
            out_of_range |= series < min_val
        if max_val is not None:
            out_of_range |= series > max_val

        combined = null_mask | out_of_range
        bad_rows = self.df[combined]
        passed = len(bad_rows) == 0
        failures = [
            {"row_index": int(i), "value": self.df.loc[i, column]}
            for i in bad_rows.index
        ]
        bounds = f"[{min_val}, {max_val}]"
        summary = (
            f"All values in '{column}' within range {bounds}"
            if passed
            else f"{len(bad_rows)} value(s) in '{column}' outside range {bounds}"
        )
        return ValidationResult(
            rule="numeric_range_check", passed=passed, failures=failures, summary=summary
        )

    def check_date_format(
        self, column: str, fmt: str = "%Y-%m-%d"
    ) -> ValidationResult:
        """Fail if *column* contains values that don't parse as *fmt*."""
        if column not in self.df.columns:
            return self._column_missing(column, "date_format_check")
        failures = []
        for idx, val in self.df[column].dropna().items():
            try:
                pd.to_datetime(str(val), format=fmt)
            except (ValueError, TypeError):
                failures.append({"row_index": int(idx), "value": str(val), "expected_format": fmt})

        passed = len(failures) == 0
        summary = (
            f"All dates in '{column}' match format '{fmt}'"
            if passed
            else f"{len(failures)} date(s) in '{column}' do not match format '{fmt}'"
        )
        return ValidationResult(
            rule="date_format_check", passed=passed, failures=failures, summary=summary
        )

    def check_email_format(self, column: str) -> ValidationResult:
        """Fail if non-null values in *column* don't look like valid emails."""
        if column not in self.df.columns:
            return self._column_missing(column, "email_format_check")
        pattern = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
        failures = []
        for idx, val in self.df[column].dropna().items():
            if not pattern.match(str(val).strip()):
                failures.append({"row_index": int(idx), "value": str(val)})

        passed = len(failures) == 0
        summary = (
            f"All non-null emails in '{column}' are valid"
            if passed
            else f"{len(failures)} invalid email(s) in '{column}'"
        )
        return ValidationResult(
            rule="email_format_check", passed=passed, failures=failures, summary=summary
        )

    def check_referential_integrity(
        self,
        fk_column: str,
        reference_df: pd.DataFrame,
        pk_column: str,
        allow_null: bool = True,
    ) -> ValidationResult:
        """Fail if *fk_column* values don't exist in *reference_df*[*pk_column*]."""
        if fk_column not in self.df.columns:
            return self._column_missing(fk_column, "referential_integrity_check")
        ref_values = set(reference_df[pk_column].dropna().astype(str).unique())
        child = self.df[fk_column]
        if allow_null:
            child = child.dropna()
        orphans = child[~child.astype(str).isin(ref_values)]
        passed = len(orphans) == 0
        failures = [
            {"row_index": int(i), "orphan_value": self.df.loc[i, fk_column]}
            for i in orphans.index
        ]
        summary = (
            f"All '{fk_column}' values reference valid '{pk_column}'"
            if passed
            else f"{len(orphans)} orphaned '{fk_column}' value(s) found"
        )
        return ValidationResult(
            rule="referential_integrity_check",
            passed=passed,
            failures=failures,
            summary=summary,
        )

    def check_no_future_dates(self, column: str) -> ValidationResult:
        """Fail if *column* contains dates in the future relative to today."""
        if column not in self.df.columns:
            return self._column_missing(column, "no_future_dates_check")
        today = pd.Timestamp.today().normalize()
        parsed = pd.to_datetime(self.df[column], errors="coerce")
        future_mask = parsed > today
        bad = self.df[future_mask]
        passed = len(bad) == 0
        failures = [
            {"row_index": int(i), "value": str(self.df.loc[i, column])} for i in bad.index
        ]
        summary = (
            f"No future dates in '{column}'"
            if passed
            else f"{len(bad)} future date(s) found in '{column}'"
        )
        return ValidationResult(
            rule="no_future_dates_check", passed=passed, failures=failures, summary=summary
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _column_missing(self, column: str, rule: str) -> ValidationResult:
        return ValidationResult(
            rule=rule,
            passed=False,
            failures=[{"error": f"Column '{column}' not found in DataFrame"}],
            summary=f"Column '{column}' not found",
        )
