"""Session-scoped fixtures — DataFrames loaded once for the entire test run."""
import sys
from pathlib import Path

import pandas as pd
import pytest

# Make src importable regardless of how pytest is invoked
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.utils.data_loader import load


# ── Bronze ─────────────────────────────────────────────────────────────────

@pytest.fixture(scope="session")
def bronze_suppliers() -> pd.DataFrame:
    return load("bronze", "suppliers")


@pytest.fixture(scope="session")
def bronze_parts() -> pd.DataFrame:
    return load("bronze", "parts")


@pytest.fixture(scope="session")
def bronze_work_orders() -> pd.DataFrame:
    return load("bronze", "work_orders")


# ── Silver ─────────────────────────────────────────────────────────────────

@pytest.fixture(scope="session")
def silver_suppliers() -> pd.DataFrame:
    return load("silver", "suppliers")


@pytest.fixture(scope="session")
def silver_parts() -> pd.DataFrame:
    return load("silver", "parts")


@pytest.fixture(scope="session")
def silver_work_orders() -> pd.DataFrame:
    return load("silver", "work_orders")


# ── Gold ───────────────────────────────────────────────────────────────────

@pytest.fixture(scope="session")
def gold_metrics() -> pd.DataFrame:
    return load("gold", "production_metrics")
