from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path


_KNOWN_EXCEPTION_NAMES = [
    "FileNotFoundError",
    "ModuleNotFoundError",
    "ImportError",
    "AttributeError",
    "KeyError",
    "TypeError",
    "OSError",
    "AssertionError",
    "ValueError",
    "RuntimeError",
    "PermissionError",
    "NotImplementedError",
    "IndexError",
    "StopIteration",
    "TimeoutError",
    "ConnectionError",
    "NameError",
]

_LAYER_KEYWORDS = {"bronze", "silver", "gold", "integration", "sql"}


@dataclass
class TestResult:
    node_id: str
    outcome: str
    layer: str
    error_class: str
    error_message: str
    traceback: str
    test_file: Path
    duration: float


def _infer_layer_from_keywords(keywords: list[str]) -> str:
    for kw in keywords:
        if kw in _LAYER_KEYWORDS:
            return kw
    return ""


def _infer_layer_from_path(node_id: str) -> str:
    for layer in _LAYER_KEYWORDS:
        if f"/{layer}/" in node_id or f"tests/{layer}" in node_id:
            return layer
    return "unknown"


def _extract_error_class(longrepr: str) -> str:
    for line in longrepr.splitlines():
        for name in _KNOWN_EXCEPTION_NAMES:
            if name in line:
                return name
        # catch duckdb-style errors like duckdb.BinderException
        if "duckdb" in line.lower() and "Exception" in line:
            parts = line.strip().split(":")
            candidate = parts[0].strip()
            if "." in candidate:
                candidate = candidate.split(".")[-1].strip()
            if candidate:
                return candidate
    return "UnknownError"


def _extract_error_message(longrepr: str) -> str:
    for line in longrepr.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("E   ") and "AssertionError" not in stripped:
            pass
        if stripped.startswith("E   ") or stripped.startswith("E "):
            return stripped.lstrip("E").strip()
    # fallback: last non-blank line
    lines = [l.strip() for l in longrepr.splitlines() if l.strip()]
    return lines[-1] if lines else ""


def _parse_test(test: dict, repo_root: Path) -> TestResult:
    node_id = test.get("nodeid", "")
    outcome = test.get("outcome", "unknown")
    duration = test.get("duration", 0.0) or 0.0
    raw_kw = test.get("keywords", {})
    keywords = list(raw_kw.keys()) if isinstance(raw_kw, dict) else list(raw_kw)

    layer = _infer_layer_from_keywords(keywords)
    if not layer:
        layer = _infer_layer_from_path(node_id)

    longrepr = ""
    error_class = ""
    error_message = ""

    call_phase = test.get("call") or {}
    if isinstance(call_phase, dict):
        longrepr = call_phase.get("longrepr") or ""
    if not longrepr:
        setup_phase = test.get("setup") or {}
        if isinstance(setup_phase, dict):
            longrepr = setup_phase.get("longrepr") or ""

    if longrepr and isinstance(longrepr, dict):
        longrepr = str(longrepr)

    if outcome in ("failed", "error") and longrepr:
        error_class = _extract_error_class(longrepr)
        error_message = _extract_error_message(longrepr)

    file_part = node_id.split("::")[0] if "::" in node_id else node_id
    test_file = Path(file_part)

    return TestResult(
        node_id=node_id,
        outcome=outcome,
        layer=layer,
        error_class=error_class,
        error_message=error_message,
        traceback=longrepr if isinstance(longrepr, str) else str(longrepr),
        test_file=test_file,
        duration=float(duration),
    )


class TestRunner:
    def __init__(self, repo_root: Path):
        self.repo_root = repo_root
        self._raw_report_path = repo_root / "reports" / "_healing_raw.json"

    def run_suite(self, target: str = "tests/") -> list[TestResult]:
        return self._run([target])

    def run_single(self, node_id: str) -> TestResult | None:
        results = self._run([node_id])
        for r in results:
            if r.node_id == node_id:
                return r
        return results[0] if results else None

    def _run(self, args: list[str]) -> list[TestResult]:
        self._raw_report_path.parent.mkdir(parents=True, exist_ok=True)

        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tmp:
            report_file = tmp.name

        cmd = [
            sys.executable, "-m", "pytest",
            "--json-report",
            f"--json-report-file={report_file}",
            "--tb=long",
            "-q",
            *args,
        ]

        subprocess.run(
            cmd,
            cwd=self.repo_root,
            capture_output=True,
            text=True,
        )

        report_path = Path(report_file)
        if not report_path.exists():
            return []

        raw = report_path.read_text(encoding="utf-8")
        report_path.unlink(missing_ok=True)

        self._raw_report_path.write_text(raw, encoding="utf-8")

        data = json.loads(raw)
        tests = data.get("tests", [])
        return [_parse_test(t, self.repo_root) for t in tests]
