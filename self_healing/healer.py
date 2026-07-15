from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from .runner import TestResult

_API_URL = "https://api.anthropic.com/v1/messages"
_MODEL = "claude-haiku-4-5-20251001"

_PROMPT_TEMPLATE = """\
A data quality pytest test failed with an INFRASTRUCTURE error (not a data assertion).

Test: {node_id}
Layer: {layer}
Error class: {error_class}
Error message: {error_message}

Full traceback:
{traceback}

Test file source:
{source}

RULES:
- This is an INFRASTRUCTURE failure — do NOT suggest relaxing data thresholds
- Do NOT modify silver/gold test conditions
- Only suggest: pip install, path corrections, column name fixes, or type cast fixes

Reply with ONLY a JSON object:
{{"fix_type": "pip_install|path_fix|column_fix|cast_fix|none", "description": "one sentence", "command": "exact shell command or empty string", "safe_to_apply": true|false, "reasoning": "one sentence"}}"""


@dataclass
class FixSuggestion:
    success: bool
    fix_type: str
    description: str
    command: str
    safe_to_apply: bool
    reasoning: str


def _no_key_suggestion(reason: str) -> FixSuggestion:
    return FixSuggestion(
        success=False,
        fix_type="none",
        description=reason,
        command="",
        safe_to_apply=False,
        reasoning=reason,
    )


def _read_source(test_file: Path, repo_root: Path) -> str:
    candidates = [
        repo_root / test_file,
        test_file if test_file.is_absolute() else Path.cwd() / test_file,
    ]
    for p in candidates:
        if p.exists():
            try:
                return p.read_text(encoding="utf-8")
            except OSError:
                pass
    return "(source not available)"


class ClaudeDQHealer:
    def suggest_fix(self, result: TestResult, repo_root: Path) -> FixSuggestion:
        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        if not api_key:
            return _no_key_suggestion("ANTHROPIC_API_KEY not set — skipping Claude suggestion.")

        source = _read_source(result.test_file, repo_root)

        prompt = _PROMPT_TEMPLATE.format(
            node_id=result.node_id,
            layer=result.layer,
            error_class=result.error_class,
            error_message=result.error_message,
            traceback=result.traceback[:8000],
            source=source[:6000],
        )

        payload = json.dumps({
            "model": _MODEL,
            "max_tokens": 512,
            "messages": [{"role": "user", "content": prompt}],
        }).encode("utf-8")

        req = urllib.request.Request(
            _API_URL,
            data=payload,
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                body = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            return _no_key_suggestion(f"API HTTP error {exc.code}: {exc.reason}")
        except Exception as exc:
            return _no_key_suggestion(f"API call failed: {exc}")

        content_blocks = body.get("content", [])
        raw_text = ""
        for block in content_blocks:
            if isinstance(block, dict) and block.get("type") == "text":
                raw_text = block.get("text", "")
                break

        match = re.search(r"\{.*\}", raw_text, re.DOTALL)
        if not match:
            return _no_key_suggestion("Could not parse JSON from response.")

        try:
            data = json.loads(match.group())
        except json.JSONDecodeError:
            return _no_key_suggestion("Malformed JSON in response.")

        return FixSuggestion(
            success=True,
            fix_type=data.get("fix_type", "none"),
            description=data.get("description", ""),
            command=data.get("command", ""),
            safe_to_apply=bool(data.get("safe_to_apply", False)),
            reasoning=data.get("reasoning", ""),
        )
