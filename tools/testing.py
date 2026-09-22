"""Test discovery and execution.

Result counts are parsed from runner output rather than trusted from an exit code
alone: "0 tests ran" and "12 tests passed" are both exit 0, and only one of them
is evidence that a fix works.
"""

from __future__ import annotations

import json
import re
import sys
from typing import Any

from core.errors import ToolError
from tools.context import ToolContext

# The interpreter running Yukti, not whatever `python` resolves to on PATH. A bare
# `python` picks up the system interpreter, which will not have the project's
# dependencies installed and fails at import rather than at the assertion.
PYTHON = sys.executable

_PYTEST_COUNT = re.compile(r"(\d+)\s+(passed|failed|error|errors|skipped|xfailed|xpassed)")
_VITEST_COUNT = re.compile(r"Tests\s+(?:(\d+)\s+failed.*?\|\s*)?(\d+)\s+passed", re.IGNORECASE)


def detect_test_framework(ctx: ToolContext) -> dict[str, Any]:
    workspace = ctx.workspace
    if (workspace / "pytest.ini").exists() or (workspace / "conftest.py").exists():
        return {"framework": "pytest", "command": [PYTHON, "-m", "pytest"]}

    pyproject = workspace / "pyproject.toml"
    if pyproject.exists() and "pytest" in pyproject.read_text(errors="replace"):
        return {"framework": "pytest", "command": [PYTHON, "-m", "pytest"]}

    package_json = workspace / "package.json"
    if package_json.exists():
        try:
            scripts = json.loads(package_json.read_text(errors="replace")).get("scripts", {})
        except json.JSONDecodeError:
            scripts = {}
        if "test" in scripts:
            return {"framework": "npm", "command": ["npm", "test"]}

    if any(workspace.rglob("test_*.py")) or any(workspace.rglob("*_test.py")):
        return {"framework": "pytest", "command": [PYTHON, "-m", "pytest"]}

    return {"framework": "unknown", "command": []}


def _parse_counts(framework: str, output: str) -> dict[str, int]:
    counts = {"passed": 0, "failed": 0, "errors": 0, "skipped": 0}
    if framework == "pytest":
        for value, label in _PYTEST_COUNT.findall(output):
            key = {"error": "errors", "errors": "errors", "xfailed": "skipped",
                   "xpassed": "passed"}.get(label, label)
            if key in counts:
                counts[key] += int(value)
    elif framework == "npm" and (match := _VITEST_COUNT.search(output)):
        counts["failed"] = int(match.group(1) or 0)
        counts["passed"] = int(match.group(2) or 0)
    return counts


def run_tests(
    ctx: ToolContext, target: str | None = None, *, timeout_s: int | None = None
) -> dict[str, Any]:
    """Run the test suite, optionally narrowed to a path or -k expression."""
    detected = detect_test_framework(ctx)
    framework = detected["framework"]
    if framework == "unknown":
        raise ToolError("no test framework detected in this repository")

    argv = list(detected["command"])
    if framework == "pytest":
        argv += ["-q", "--no-header", "-p", "no:cacheprovider"]
        if target:
            argv += ([target] if "::" in target or target.endswith(".py") else ["-k", target])
    elif target:
        argv += ["--", target]

    result = ctx.executor.run(argv, timeout_s=timeout_s or ctx.timeout_s)
    output = f"{result.stdout}\n{result.stderr}".strip()
    counts = _parse_counts(framework, output)
    executed = counts["passed"] + counts["failed"] + counts["errors"]

    return {
        "framework": framework,
        "command": argv,
        "exit_code": result.exit_code,
        "timed_out": result.timed_out,
        "passed": counts["passed"],
        "failed": counts["failed"],
        "errors": counts["errors"],
        "skipped": counts["skipped"],
        "tests_executed": executed,
        # Exit code alone is not sufficient: a suite that collected nothing also
        # exits non-zero on pytest, and a green exit with zero tests proves nothing.
        "success": result.exit_code == 0 and not result.timed_out and executed > 0,
        "output_tail": output[-4000:],
        "duration_ms": result.duration_ms,
    }
