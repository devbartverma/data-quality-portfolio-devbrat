#!/usr/bin/env python3
"""
Self-healing DQ test runner.

Usage:
  python3 run_self_healing.py              # run full suite
  python3 run_self_healing.py tests/silver # run specific layer
  python3 run_self_healing.py --dry-run    # classify only, no Claude calls
"""
import sys
from pathlib import Path

from self_healing.engine import SelfHealingEngine


def main() -> None:
    repo_root = Path(__file__).parent
    target = "tests/"
    dry_run = False

    for arg in sys.argv[1:]:
        if arg == "--dry-run":
            dry_run = True
        elif not arg.startswith("--"):
            target = arg

    if dry_run:
        from self_healing.runner import TestRunner
        from self_healing.classifier import classify

        runner = TestRunner(repo_root)
        results = runner.run_suite(target)
        for r in results:
            c = classify(r)
            print(f"[dry-run] {r.node_id}")
            print(f"          outcome={r.outcome}  layer={r.layer}  error={r.error_class}")
            print(f"          decision={c.decision.value}  reason={c.reason}")
            print()
        return

    engine = SelfHealingEngine(repo_root)
    report_path = engine.run(target)
    print(f"\nOpen report: {report_path}")


if __name__ == "__main__":
    main()
