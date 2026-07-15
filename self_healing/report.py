from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .classifier import Classification, HealDecision
from .healer import FixSuggestion
from .runner import TestResult


@dataclass
class HealingAttempt:
    attempt_number: int
    fix_suggestion: FixSuggestion
    applied: bool
    apply_output: str
    rerun_outcome: str


@dataclass
class HealingRecord:
    test_result: TestResult
    classification: Classification
    attempts: list[HealingAttempt]
    final_outcome: str
    artifact_path: str


_OUTCOME_COLORS = {
    "healed": "#2e7d32",
    "passed": "#2e7d32",
    "must_fail": "#b71c1c",
    "exhausted": "#e65100",
    "unknown": "#616161",
    "pass": "#2e7d32",
}

_OUTCOME_BADGES = {
    "healed": ("Healed", "#c8e6c9", "#2e7d32"),
    "passed": ("Passed", "#c8e6c9", "#2e7d32"),
    "must_fail": ("Must-Fail", "#ffcdd2", "#b71c1c"),
    "exhausted": ("Exhausted", "#ffe0b2", "#e65100"),
    "unknown": ("Unknown", "#f5f5f5", "#616161"),
    "pass": ("Passed", "#c8e6c9", "#2e7d32"),
}

_CSS = """
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #f5f5f5; color: #212121; }
.header { background: #1a237e; color: #fff; padding: 24px 32px; }
.header h1 { font-size: 1.5rem; font-weight: 600; }
.header .meta { font-size: 0.82rem; margin-top: 6px; opacity: 0.75; }
.banner { display: flex; gap: 16px; padding: 20px 32px; background: #fff; border-bottom: 1px solid #e0e0e0; flex-wrap: wrap; }
.stat { padding: 12px 20px; border-radius: 6px; min-width: 110px; text-align: center; }
.stat .num { font-size: 2rem; font-weight: 700; }
.stat .lbl { font-size: 0.75rem; text-transform: uppercase; letter-spacing: 0.06em; margin-top: 2px; }
.stat-pass { background: #e8f5e9; color: #2e7d32; }
.stat-heal { background: #e3f2fd; color: #1565c0; }
.stat-mf   { background: #ffebee; color: #b71c1c; }
.stat-ex   { background: #fff3e0; color: #e65100; }
.stat-unk  { background: #f5f5f5; color: #616161; }
.section { padding: 24px 32px; }
.section h2 { font-size: 1rem; font-weight: 600; margin-bottom: 12px; color: #424242; }
table { width: 100%; border-collapse: collapse; background: #fff; border-radius: 8px; overflow: hidden; box-shadow: 0 1px 3px rgba(0,0,0,.08); font-size: 0.87rem; }
th { background: #eeeeee; padding: 10px 14px; text-align: left; font-weight: 600; color: #424242; border-bottom: 2px solid #e0e0e0; }
td { padding: 10px 14px; border-bottom: 1px solid #f0f0f0; vertical-align: top; }
tr:last-child td { border-bottom: none; }
.badge { display: inline-block; padding: 2px 10px; border-radius: 12px; font-size: 0.78rem; font-weight: 600; }
.nodeid { font-family: 'SFMono-Regular', Consolas, monospace; font-size: 0.80rem; word-break: break-all; }
.layer-pill { display: inline-block; padding: 1px 8px; border-radius: 10px; font-size: 0.75rem; font-weight: 600; background: #e8eaf6; color: #3949ab; }
details { margin-top: 6px; }
summary { cursor: pointer; font-size: 0.80rem; color: #1565c0; }
pre { background: #f8f8f8; border: 1px solid #e0e0e0; border-radius: 4px; padding: 8px; font-size: 0.78rem; overflow-x: auto; white-space: pre-wrap; word-break: break-all; margin-top: 6px; max-height: 260px; overflow-y: auto; }
.reason { font-size: 0.82rem; color: #616161; font-style: italic; }
"""


def _badge(outcome: str) -> str:
    label, bg, fg = _OUTCOME_BADGES.get(outcome, ("Unknown", "#f5f5f5", "#616161"))
    return f'<span class="badge" style="background:{bg};color:{fg}">{label}</span>'


def _sanitize(node_id: str) -> str:
    return re.sub(r"[^\w\-]", "_", node_id)[:120]


def _fix_row(attempt: HealingAttempt) -> str:
    f = attempt.fix_suggestion
    applied_txt = "yes" if attempt.applied else "no"
    return (
        f"<tr><td>#{attempt.attempt_number}</td>"
        f"<td>{f.fix_type}</td>"
        f"<td>{f.description}</td>"
        f"<td><code>{f.command or '—'}</code></td>"
        f"<td>{applied_txt}</td>"
        f"<td>{attempt.rerun_outcome}</td></tr>"
    )


class HealingReport:
    def __init__(self, repo_root: Path):
        self.repo_root = repo_root
        self._records: list[HealingRecord] = []

    def add(self, record: HealingRecord) -> None:
        self._records.append(record)

    def generate(self) -> Path:
        out_dir = self.repo_root / "reports" / "healing"
        out_dir.mkdir(parents=True, exist_ok=True)

        passed = [r for r in self._records if r.final_outcome in ("passed", "pass")]
        healed = [r for r in self._records if r.final_outcome == "healed"]
        must_fail = [r for r in self._records if r.final_outcome == "must_fail"]
        exhausted = [r for r in self._records if r.final_outcome == "exhausted"]
        unknown = [r for r in self._records if r.final_outcome == "unknown"]

        ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

        rows = ""
        for rec in self._records:
            tr = rec.test_result
            fo = rec.final_outcome

            attempt_detail = ""
            if rec.attempts:
                fix_rows = "".join(_fix_row(a) for a in rec.attempts)
                attempt_detail = (
                    "<details><summary>Attempts</summary>"
                    "<table><tr><th>#</th><th>fix_type</th><th>description</th>"
                    "<th>command</th><th>applied</th><th>rerun</th></tr>"
                    f"{fix_rows}</table></details>"
                )

            reason_txt = ""
            if rec.classification.reason:
                reason_txt = f'<div class="reason">{rec.classification.reason}</div>'

            rows += (
                f"<tr>"
                f"<td><span class='nodeid'>{tr.node_id}</span></td>"
                f"<td><span class='layer-pill'>{tr.layer}</span></td>"
                f"<td>{rec.classification.decision.value}</td>"
                f"<td>{_badge(fo)}</td>"
                f"<td>{len(rec.attempts)}</td>"
                f"<td>{reason_txt}{attempt_detail}</td>"
                f"</tr>\n"
            )

        html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Self-Healing DQ Report</title>
<style>{_CSS}</style>
</head>
<body>
<div class="header">
  <h1>Self-Healing DQ Report</h1>
  <div class="meta">Generated: {ts} &nbsp;|&nbsp; Repo: {self.repo_root}</div>
</div>
<div class="banner">
  <div class="stat stat-pass"><div class="num">{len(passed)}</div><div class="lbl">Passed</div></div>
  <div class="stat stat-heal"><div class="num">{len(healed)}</div><div class="lbl">Healed</div></div>
  <div class="stat stat-mf"><div class="num">{len(must_fail)}</div><div class="lbl">Must-Fail</div></div>
  <div class="stat stat-ex"><div class="num">{len(exhausted)}</div><div class="lbl">Exhausted</div></div>
  <div class="stat stat-unk"><div class="num">{len(unknown)}</div><div class="lbl">Unknown</div></div>
</div>
<div class="section">
  <h2>Test Results</h2>
  <table>
    <thead>
      <tr>
        <th>Test</th><th>Layer</th><th>Classification</th>
        <th>Status</th><th>Attempts</th><th>Details</th>
      </tr>
    </thead>
    <tbody>
{rows}    </tbody>
  </table>
</div>
</body>
</html>"""

        html_path = out_dir / "healing_report.html"
        html_path.write_text(html, encoding="utf-8")

        summary = {
            "generated_at": ts,
            "repo_root": str(self.repo_root),
            "totals": {
                "passed": len(passed),
                "healed": len(healed),
                "must_fail": len(must_fail),
                "exhausted": len(exhausted),
                "unknown": len(unknown),
                "total": len(self._records),
            },
            "tests": [
                {
                    "node_id": r.test_result.node_id,
                    "layer": r.test_result.layer,
                    "outcome": r.test_result.outcome,
                    "final_outcome": r.final_outcome,
                    "classification": r.classification.decision.value,
                    "reason": r.classification.reason,
                    "attempts": len(r.attempts),
                    "artifact": r.artifact_path,
                }
                for r in self._records
            ],
        }

        json_path = out_dir / "healing_summary.json"
        json_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")

        return html_path
