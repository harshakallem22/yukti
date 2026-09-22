"""Report rendering and baseline comparison."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPORT_DIR = Path(__file__).resolve().parent / "reports"

_PERCENT_KEYS = [
    ("task_success_rate", "Task Success"),
    ("test_pass_rate", "Test Pass Rate"),
    ("patch_correctness_rate", "Patch Correctness"),
    ("regression_safety_rate", "Regression Safety"),
    ("file_localization_precision", "File Localization P"),
    ("file_localization_recall", "File Localization R"),
    ("policy_compliance_rate", "Policy Compliance"),
    ("approval_compliance_rate", "Approval Compliance"),
]
_RAW_KEYS = [
    ("avg_steps", "Average Steps"),
    ("avg_tool_calls", "Average Tool Calls"),
    ("avg_duplicate_tool_calls", "Avg Duplicate Calls"),
    ("avg_latency_ms", "Average Latency (ms)"),
]

# Metrics where an increase is a regression, not an improvement.
_LOWER_IS_BETTER = {"avg_steps", "avg_tool_calls", "avg_duplicate_tool_calls",
                    "avg_latency_ms", "avg_cost_usd"}


def render(suite: str, summary: dict[str, Any]) -> str:
    lines = [f"Evaluation Suite: {suite}", f"Cases: {summary.get('cases', 0)}", ""]
    if summary.get("demo_mode"):
        lines.insert(0, "*** DEMO MODE — scripted provider. These are NOT real metrics. ***\n")

    for key, label in _PERCENT_KEYS:
        lines.append(f"{label + ':':<26}{summary.get(key, 0.0) * 100:6.1f}%")
    lines.append("")
    for key, label in _RAW_KEYS:
        lines.append(f"{label + ':':<26}{summary.get(key, 0.0):>7.1f}")
    lines.append(f"{'Average Cost:':<26}{summary.get('avg_cost_usd', 0.0):>7.4f} USD")

    if failures := summary.get("failure_categories"):
        lines.append("\nFailure categories:")
        for category, count in sorted(failures.items(), key=lambda kv: -kv[1]):
            lines.append(f"  {category:<26}{count}")
    return "\n".join(lines)


def compare(current: dict[str, Any], baseline: dict[str, Any]) -> str:
    """Report both directions. An improvement without its cost is marketing."""
    lines = ["", "Comparison against baseline", "-" * 52]
    for key, label in [*_PERCENT_KEYS, *_RAW_KEYS, ("avg_cost_usd", "Average Cost")]:
        if key not in baseline:
            continue
        now, before = current.get(key, 0.0), baseline[key]
        delta = now - before
        scale = 100 if key in dict(_PERCENT_KEYS) else 1
        improved = (delta < 0) if key in _LOWER_IS_BETTER else (delta > 0)
        marker = "  " if abs(delta) < 1e-9 else ("improved" if improved else "REGRESSED")
        lines.append(
            f"{label + ':':<26}{before * scale:8.2f} -> {now * scale:8.2f}"
            f"  ({delta * scale:+.2f})  {marker}"
        )
    return "\n".join(lines)


def save(suite: str, payload: dict[str, Any]) -> Path:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    path = REPORT_DIR / f"{suite}-{stamp}.json"
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    return path


def load_baseline(path: Path) -> dict[str, Any]:
    payload: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    summary: dict[str, Any] = payload.get("summary", payload)
    return summary
