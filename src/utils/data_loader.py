"""Loads CSV data files from the medallion data layers."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import pandas as pd

DATA_ROOT = Path(__file__).resolve().parents[2] / "data"

_LAYER_TABLES = {
    "bronze": {
        "suppliers": "suppliers_raw.csv",
        "parts": "parts_catalog_raw.csv",
        "work_orders": "work_orders_raw.csv",
    },
    "silver": {
        "suppliers": "suppliers_cleansed.csv",
        "parts": "parts_catalog_cleansed.csv",
        "work_orders": "work_orders_cleansed.csv",
    },
    "gold": {
        "production_metrics": "production_metrics.csv",
    },
}


def load(layer: str, table: str, **read_csv_kwargs) -> pd.DataFrame:
    """Return a DataFrame for *layer*/*table*.

    Example::

        df = load("silver", "suppliers")
    """
    layer = layer.lower()
    table = table.lower()
    if layer not in _LAYER_TABLES:
        raise ValueError(f"Unknown layer '{layer}'. Choose from: {list(_LAYER_TABLES)}")
    if table not in _LAYER_TABLES[layer]:
        raise ValueError(
            f"Unknown table '{table}' for layer '{layer}'. "
            f"Choose from: {list(_LAYER_TABLES[layer])}"
        )
    path = DATA_ROOT / layer / _LAYER_TABLES[layer][table]
    return pd.read_csv(path, **read_csv_kwargs)


def load_all(layer: str, **read_csv_kwargs) -> dict[str, pd.DataFrame]:
    """Return a dict of all DataFrames for *layer*."""
    return {table: load(layer, table, **read_csv_kwargs) for table in _LAYER_TABLES[layer]}
