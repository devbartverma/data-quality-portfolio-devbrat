from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

from .classifier import HealDecision, Classification, classify
from .fix_applicator import FixApplicator
from .healer import ClaudeDQHealer
from .report import HealingAttempt, HealingRecord, HealingReport
from .runner import TestResult, TestRunner


class SelfHealingEngine:
    MAX_ATTEMPTS = 3

    def __init__(self, repo_root: Path):
        self.repo_root = repo_root
        self.runner = TestRunner(repo_root)
        self.healer = ClaudeDQHealer()
        self.applicator = FixApplicator()
        self.report = HealingReport(repo_root)

    def run(self, target: str = "tests/") -> Path:
        print(f"[self-heal] Running test suite: {target}")
        results = self.runner.run_suite(target)

        passed = [r for r in results if r.outcome == "passed"]
        failed = [r for r in results if r.outcome in ("failed", "error")]

        print(f"[self-heal] {len(passed)} passed, {len(failed)} failed")

        for result in passed:
            self.report.add(HealingRecord(result, Classification(HealDecision.PASS, ""), [], "passed", ""))

        for result in failed:
            classification = classify(result)

            if classification.decision == HealDecision.MUST_FAIL:
                print(f"[self-heal] MUST-FAIL: {result.node_id} — {classification.reason}")
                self.report.add(HealingRecord(result, classification, [], "must_fail", ""))
                continue

            if classification.decision != HealDecision.HEALABLE:
                self.report.add(HealingRecord(result, classification, [], "unknown", ""))
                continue

            print(f"[self-heal] Attempting to heal: {result.node_id}")
            attempts: list[HealingAttempt] = []
            healed = False
            current_result = result

            for attempt_num in range(1, self.MAX_ATTEMPTS + 1):
                print(f"[self-heal]   Attempt {attempt_num}/{self.MAX_ATTEMPTS}")
                fix = self.healer.suggest_fix(current_result, self.repo_root)
                applied, apply_output = self.applicator.apply(fix)

                rerun_outcome = "not_run"
                if applied:
                    rerun = self.runner.run_single(result.node_id)
                    rerun_outcome = rerun.outcome if rerun else "error"
                    if rerun and rerun_outcome == "failed":
                        current_result = rerun

                attempts.append(HealingAttempt(attempt_num, fix, applied, apply_output, rerun_outcome))

                if rerun_outcome == "passed":
                    healed = True
                    print(f"[self-heal]   HEALED on attempt {attempt_num}")
                    break

            final = "healed" if healed else "exhausted"
            artifact = self._write_artifact(result, attempts, healed)
            self.report.add(HealingRecord(result, classification, attempts, final, artifact))

        report_path = self.report.generate()
        print(f"[self-heal] Report: {report_path}")
        return report_path

    def _write_artifact(self, result: TestResult, attempts: list[HealingAttempt], healed: bool) -> str:
        out_dir = self.repo_root / "reports" / "healing"
        out_dir.mkdir(parents=True, exist_ok=True)

        safe = re.sub(r"[^\w\-]", "_", result.node_id)[:100]
        suffix = "HEALED" if healed else "FAILED"
        artifact_path = out_dir / f"{safe}-{suffix}.md"

        ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

        lines = [
            f"# {suffix}: {result.node_id}",
            "",
            f"- **Layer:** {result.layer}",
            f"- **Error class:** {result.error_class}",
            f"- **Timestamp:** {ts}",
            "",
            "## Original error",
            "",
            "```",
            result.error_message,
            "```",
            "",
            "## Healing attempts",
            "",
        ]

        for a in attempts:
            f = a.fix_suggestion
            lines += [
                f"### Attempt {a.attempt_number}",
                f"- fix_type: `{f.fix_type}`",
                f"- description: {f.description}",
                f"- command: `{f.command or '(none)'}`",
                f"- applied: {'yes' if a.applied else 'no'}",
                f"- apply output: {a.apply_output}",
                f"- rerun outcome: `{a.rerun_outcome}`",
                f"- reasoning: {f.reasoning}",
                "",
            ]

        if not healed:
            lines += [
                "## Result",
                "",
                "Claude couldn't do it, check manually.",
                "",
            ]
        else:
            winning = next((a for a in attempts if a.rerun_outcome == "passed"), None)
            if winning:
                lines += [
                    "## Result",
                    "",
                    f"Healed on attempt {winning.attempt_number} via `{winning.fix_suggestion.fix_type}`.",
                    "",
                ]

        artifact_path.write_text("\n".join(lines), encoding="utf-8")
        return str(artifact_path.relative_to(self.repo_root))
