"""Evaluation harness.

Reset → run → capture → grade with hidden tests → persist → aggregate.
"""

from __future__ import annotations

import subprocess
import time
from dataclasses import asdict
from datetime import UTC, datetime
from typing import Any

from agent.prompts import PROMPT_VERSION
from agent.providers import build_provider
from agent.runner import Runner
from agent.state import Issue
from apps.api.app.db import init_db, session_scope
from apps.api.app.models import EvaluationResult, EvaluationRun
from core.config import get_settings
from evals.cases import REPO_ROOT, EvalCase
from evals.evaluators import CaseMetrics, evaluate


class DemoModeRefused(RuntimeError):
    """Scoring a scripted run would be a fabricated metric."""


def git_sha() -> str:
    try:
        result = subprocess.run(  # noqa: S603
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=REPO_ROOT, capture_output=True, text=True, timeout=10, check=False,
        )
        return result.stdout.strip() or "unknown"
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def run_case(case: EvalCase, runner: Runner) -> CaseMetrics:
    issue = Issue(
        title=case.issue["title"],
        body=case.issue["body"],
        repro_steps=case.issue.get("repro_steps"),
        expected_behavior=case.issue.get("expected_behavior"),
    )
    run_id = f"eval-{case.id}-{int(time.time())}"
    started = time.monotonic()

    # Each case gets a fresh clone of the pristine benchmark repo, so cases cannot
    # contaminate each other.
    handle = runner.start(source_repo=case.repo_path, issue=issue, run_id=run_id)
    latency_ms = int((time.monotonic() - started) * 1000)

    if handle.interrupted:
        # An unattended eval cannot answer an approval prompt. Treat it as a
        # policy outcome and record it rather than auto-approving, which would
        # measure a system that does not exist.
        metrics = CaseMetrics(
            case_id=case.id,
            failure_category="POLICY_VIOLATION",
            latency_ms=latency_ms,
            steps=len(handle.state.steps),
            tool_calls=handle.state.usage.tool_calls,
            cost_usd=handle.state.usage.cost_usd,
            details={"interrupted_for_approval": handle.interrupt_payload},
        )
        return metrics

    return evaluate(case, handle.state, runner.tool_history(run_id), latency_ms)


def aggregate(metrics: list[CaseMetrics]) -> dict[str, Any]:
    if not metrics:
        return {}
    n = len(metrics)

    def mean(values: list[float]) -> float:
        return round(sum(values) / n, 4)

    failures: dict[str, int] = {}
    for metric in metrics:
        if metric.failure_category:
            failures[metric.failure_category] = failures.get(metric.failure_category, 0) + 1

    return {
        "cases": n,
        "task_success_rate": mean([1.0 if m.task_success else 0.0 for m in metrics]),
        "test_pass_rate": mean([m.test_pass_rate for m in metrics]),
        "patch_correctness_rate": mean([1.0 if m.patch_correctness else 0.0 for m in metrics]),
        "regression_safety_rate": mean([1.0 if m.regression_safety else 0.0 for m in metrics]),
        "file_localization_precision": mean([m.file_localization_precision for m in metrics]),
        "file_localization_recall": mean([m.file_localization_recall for m in metrics]),
        "policy_compliance_rate": mean([1.0 if m.policy_compliance else 0.0 for m in metrics]),
        "approval_compliance_rate": mean([1.0 if m.approval_compliance else 0.0 for m in metrics]),
        "avg_steps": mean([float(m.steps) for m in metrics]),
        "avg_tool_calls": mean([float(m.tool_calls) for m in metrics]),
        "avg_duplicate_tool_calls": mean([float(m.duplicate_tool_calls) for m in metrics]),
        "avg_cost_usd": mean([m.cost_usd for m in metrics]),
        "avg_latency_ms": mean([float(m.latency_ms) for m in metrics]),
        "failure_categories": failures,
    }


def run_suite(cases: list[EvalCase], suite: str, *, allow_demo: bool = False) -> dict[str, Any]:
    settings = get_settings()
    if settings.provider == "fake" and not allow_demo:
        raise DemoModeRefused(
            "YUKTI_MODEL_PROVIDER=fake replays a canned trajectory. Scoring it would "
            "produce a fabricated benchmark number. Set a real provider, or pass "
            "--allow-demo to smoke-test the harness itself (results are marked demo)."
        )

    runner = Runner(settings, lambda: build_provider(settings))
    init_db()

    metrics: list[CaseMetrics] = []
    for index, case in enumerate(cases, start=1):
        print(f"[{index}/{len(cases)}] {case.id}: {case.title}")
        try:
            result = run_case(case, runner)
        except Exception as exc:  # noqa: BLE001 - one bad case must not kill the suite
            result = CaseMetrics(case_id=case.id, failure_category="TOOL_ERROR",
                                 details={"error": f"{type(exc).__name__}: {exc}"})
        metrics.append(result)
        print(
            f"    task_success={result.task_success} "
            f"files={result.details.get('patch_files', [])} "
            f"category={result.failure_category or '-'}"
        )

    summary = aggregate(metrics)
    summary["demo_mode"] = settings.provider == "fake"
    evaluation_id = _persist(suite, cases, metrics, summary, settings)
    summary["evaluation_run_id"] = evaluation_id
    return {"summary": summary, "metrics": [asdict(m) for m in metrics]}


def _persist(
    suite: str, cases: list[EvalCase], metrics: list[CaseMetrics], summary: dict[str, Any],
    settings: Any,
) -> str:
    by_id = {case.id: case for case in cases}
    with session_scope() as session:
        evaluation = EvaluationRun(
            suite=suite,
            git_sha=git_sha(),
            model=settings.investigator_model if settings.provider != "fake" else "scripted",
            prompt_version=PROMPT_VERSION,
            aggregate_metrics=summary,
            case_count=len(metrics),
            ended_at=datetime.now(UTC),
        )
        session.add(evaluation)
        session.flush()

        for metric in metrics:
            case = by_id.get(metric.case_id)
            session.add(
                EvaluationResult(
                    evaluation_run_id=evaluation.id,
                    case_id=metric.case_id,
                    case_hash=case.content_hash if case else "",
                    task_success=metric.task_success,
                    test_pass_rate=metric.test_pass_rate,
                    patch_correctness=metric.patch_correctness,
                    regression_safety=metric.regression_safety,
                    file_localization_precision=metric.file_localization_precision,
                    file_localization_recall=metric.file_localization_recall,
                    policy_compliance=metric.policy_compliance,
                    approval_compliance=metric.approval_compliance,
                    steps=metric.steps,
                    tool_calls=metric.tool_calls,
                    duplicate_tool_calls=metric.duplicate_tool_calls,
                    cost_usd=metric.cost_usd,
                    latency_ms=metric.latency_ms,
                    failure_category=metric.failure_category,
                    evaluator_details=metric.details,
                )
            )
        return evaluation.id
