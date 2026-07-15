from __future__ import annotations

import subprocess
import sys

from .healer import FixSuggestion


class FixApplicator:
    ALLOWED_FIX_TYPES = {"pip_install"}

    def apply(self, fix: FixSuggestion) -> tuple[bool, str]:
        if fix.fix_type not in self.ALLOWED_FIX_TYPES:
            return False, f"manual action required: {fix.description}"

        cmd = fix.command.strip()
        if not cmd.lower().startswith("pip"):
            return False, f"manual action required: command safety check failed — {cmd!r} does not start with 'pip'"

        # replace bare pip with the current interpreter's pip so the right env is targeted
        normalized = cmd.replace("pip install", f"{sys.executable} -m pip install", 1)
        if normalized == cmd:
            normalized = cmd.replace("pip3 install", f"{sys.executable} -m pip install", 1)

        try:
            result = subprocess.run(
                normalized,
                shell=True,
                capture_output=True,
                text=True,
                timeout=120,
            )
            if result.returncode == 0:
                return True, result.stdout.strip() or "pip install succeeded"
            return False, f"pip install failed (exit {result.returncode}): {result.stderr.strip()}"
        except subprocess.TimeoutExpired:
            return False, "pip install timed out after 120 s"
        except Exception as exc:
            return False, f"pip install error: {exc}"
