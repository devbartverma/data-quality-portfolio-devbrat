from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .runner import TestResult


class HealDecision(str, Enum):
    PASS = "pass"
    MUST_FAIL = "must_fail"
    HEALABLE = "healable"
    UNKNOWN = "unknown"


@dataclass
class Classification:
    decision: HealDecision
    reason: str


_INFRA_ERRORS = {
    "FileNotFoundError",
    "ModuleNotFoundError",
    "ImportError",
    "AttributeError",
    "KeyError",
    "TypeError",
    "OSError",
}

_ASSERTION_MUST_FAIL_LAYERS = {"silver", "gold", "integration", "bronze", "sql"}

_ASSERTION_REASONS = {
    "silver": "Silver/Gold hard gate — genuine data quality violation. Must remain failed.",
    "gold": "Silver/Gold hard gate — genuine data quality violation. Must remain failed.",
    "integration": "Integration E2E reconciliation failure — data pipeline issue. Must remain failed.",
    "bronze": "Bronze detection test found violation above tolerance — documented finding. Must remain failed.",
    "sql": "SQL DQ assertion fired — data violation detected by live SQL query. Must remain failed.",
}


def classify(result: TestResult) -> Classification:
    if result.outcome == "passed":
        return Classification(HealDecision.PASS, "")

    ec = result.error_class
    layer = result.layer

    if ec in _INFRA_ERRORS:
        return Classification(HealDecision.HEALABLE, "Infrastructure failure — can happen at any layer.")

    if ec == "AssertionError":
        if layer in _ASSERTION_MUST_FAIL_LAYERS:
            return Classification(HealDecision.MUST_FAIL, _ASSERTION_REASONS[layer])
        return Classification(HealDecision.MUST_FAIL, "AssertionError — data quality violation. Must remain failed.")

    if "duckdb" in ec.lower():
        return Classification(HealDecision.HEALABLE, "DuckDB engine error — infrastructure/type issue.")

    if ec != "AssertionError":
        return Classification(HealDecision.HEALABLE, f"{ec} is an infrastructure-class error.")

    return Classification(HealDecision.UNKNOWN, f"Unrecognised failure pattern: {ec} / layer={layer}")
