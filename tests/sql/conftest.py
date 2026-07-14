"""DuckDB session fixture — loads all seven CSVs as in-memory tables.

All tests in tests/sql/ use this connection. DuckDB runs entirely in-process;
no database server or network connection is required.
"""
from pathlib import Path

import duckdb
import pandas as pd
import pytest

_DATA_ROOT = Path(__file__).resolve().parents[2] / "data"

_TABLES = {
    "bronze_suppliers":  _DATA_ROOT / "bronze/suppliers_raw.csv",
    "bronze_parts":      _DATA_ROOT / "bronze/parts_catalog_raw.csv",
    "bronze_work_orders": _DATA_ROOT / "bronze/work_orders_raw.csv",
    "silver_suppliers":  _DATA_ROOT / "silver/suppliers_cleansed.csv",
    "silver_parts":      _DATA_ROOT / "silver/parts_catalog_cleansed.csv",
    "silver_work_orders": _DATA_ROOT / "silver/work_orders_cleansed.csv",
    "gold_metrics":      _DATA_ROOT / "gold/production_metrics.csv",
}


@pytest.fixture(scope="session")
def duckdb_con():
    con = duckdb.connect()
    for table_name, csv_path in _TABLES.items():
        con.register(table_name, pd.read_csv(csv_path))
    return con
