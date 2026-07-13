"""Statistical profiling: outlier detection, cardinality, IQR bounds, freshness."""
from __future__ import annotations

from typing import Optional

import pandas as pd

from .completeness_validator import ValidationResult


class StatisticalProfiler:
    """Detects statistical anomalies in a pandas DataFrame column."""

    def __init__(self, df: pd.DataFrame, table_name: str = "unknown"):
        self.df = df
        self.table_name = table_name

    # ------------------------------------------------------------------
    # Public checks
    # ------------------------------------------------------------------

    def check_zscore_outliers(
        self,
        column: str,
        threshold: float = 3.0,
    ) -> ValidationResult:
        """Flag rows where |Z-score| > *threshold* (default: 3σ)."""
        if column not in self.df.columns:
            return self._column_missing(column, "zscore_outliers_check")
        series = pd.to_numeric(self.df[column], errors="coerce").dropna()
        if len(series) < 3:
            return ValidationResult(
                rule="zscore_outliers_check",
                passed=True,
                failures=[],
                summary=f"Too few rows in '{column}' for Z-score analysis",
            )
        mean = series.mean()
        std = series.std()
        if std == 0:
            return ValidationResult(
                rule="zscore_outliers_check",
                passed=True,
                failures=[],
                summary=f"Zero variance in '{column}' — no outliers possible",
            )
        zscores = (series - mean) / std
        outlier_idx = zscores[zscores.abs() > threshold].index
        passed = len(outlier_idx) == 0
        failures = [
            {
                "row_index": int(i),
                "value": float(self.df.loc[i, column]),
                "zscore": round(float(zscores[i]), 3),
            }
            for i in outlier_idx
        ]
        summary = (
            f"No outliers (|Z|>{threshold}) in '{column}'"
            if passed
            else f"{len(outlier_idx)} outlier(s) detected in '{column}' (|Z|>{threshold})"
        )
        return ValidationResult(
            rule="zscore_outliers_check", passed=passed, failures=failures, summary=summary
        )

    def check_iqr_bounds(
        self,
        column: str,
        multiplier: float = 1.5,
    ) -> ValidationResult:
        """Flag rows outside IQR fence: [Q1 - k*IQR, Q3 + k*IQR]."""
        if column not in self.df.columns:
            return self._column_missing(column, "iqr_bounds_check")
        series = pd.to_numeric(self.df[column], errors="coerce").dropna()
        if len(series) < 4:
            return ValidationResult(
                rule="iqr_bounds_check",
                passed=True,
                failures=[],
                summary=f"Too few rows in '{column}' for IQR analysis",
            )
        q1 = series.quantile(0.25)
        q3 = series.quantile(0.75)
        iqr = q3 - q1
        lower = q1 - multiplier * iqr
        upper = q3 + multiplier * iqr
        mask = (series < lower) | (series > upper)
        bad_idx = series[mask].index
        passed = len(bad_idx) == 0
        failures = [
            {
                "row_index": int(i),
                "value": float(self.df.loc[i, column]),
                "lower_fence": round(float(lower), 4),
                "upper_fence": round(float(upper), 4),
            }
            for i in bad_idx
        ]
        summary = (
            f"No IQR outliers in '{column}' (fence=[{lower:.2f}, {upper:.2f}])"
            if passed
            else f"{len(bad_idx)} IQR outlier(s) in '{column}'"
        )
        return ValidationResult(
            rule="iqr_bounds_check", passed=passed, failures=failures, summary=summary
        )

    def check_cardinality(
        self,
        column: str,
        min_distinct: Optional[int] = None,
        max_distinct: Optional[int] = None,
    ) -> ValidationResult:
        """Fail if the number of distinct values in *column* is outside the expected range."""
        if column not in self.df.columns:
            return self._column_missing(column, "cardinality_check")
        n_distinct = int(self.df[column].nunique(dropna=True))
        too_low = min_distinct is not None and n_distinct < min_distinct
        too_high = max_distinct is not None and n_distinct > max_distinct
        passed = not too_low and not too_high
        failures = (
            []
            if passed
            else [
                {
                    "column": column,
                    "distinct_count": n_distinct,
                    "min_distinct": min_distinct,
                    "max_distinct": max_distinct,
                }
            ]
        )
        summary = (
            f"'{column}' cardinality={n_distinct} within expected range"
            if passed
            else f"'{column}' cardinality={n_distinct} outside expected range "
            f"[{min_distinct}, {max_distinct}]"
        )
        return ValidationResult(
            rule="cardinality_check", passed=passed, failures=failures, summary=summary
        )

    def check_freshness(
        self,
        timestamp_column: str,
        max_lag_hours: float = 26.0,
    ) -> ValidationResult:
        """Fail if the most recent timestamp in *timestamp_column* is older than *max_lag_hours*.

        Ensures pipeline didn't silently stop loading data.
        """
        if timestamp_column not in self.df.columns:
            return self._column_missing(timestamp_column, "freshness_check")
        parsed = pd.to_datetime(self.df[timestamp_column], errors="coerce")
        if parsed.isna().all():
            return ValidationResult(
                rule="freshness_check",
                passed=False,
                failures=[{"error": "All timestamps are null or unparseable"}],
                summary="Cannot determine freshness — no valid timestamps",
            )
        latest = parsed.max()
        now = pd.Timestamp.utcnow().tz_localize(None)
        lag_hours = (now - latest).total_seconds() / 3600
        passed = lag_hours <= max_lag_hours
        failures = (
            []
            if passed
            else [
                {
                    "latest_timestamp": str(latest),
                    "lag_hours": round(lag_hours, 2),
                    "max_lag_hours": max_lag_hours,
                }
            ]
        )
        summary = (
            f"Data is fresh: latest={latest}, lag={lag_hours:.1f}h (max={max_lag_hours}h)"
            if passed
            else f"Stale data: latest={latest}, lag={lag_hours:.1f}h > max={max_lag_hours}h"
        )
        return ValidationResult(
            rule="freshness_check", passed=passed, failures=failures, summary=summary
        )

    # ------------------------------------------------------------------

    def _column_missing(self, column: str, rule: str) -> ValidationResult:
        return ValidationResult(
            rule=rule,
            passed=False,
            failures=[{"error": f"Column '{column}' not found in DataFrame"}],
            summary=f"Column '{column}' not found",
        )
