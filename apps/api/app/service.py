"""Run orchestration and persistence.

Runs execute on a background thread so the API stays responsive. The live trace is
served from the in-memory event bus; the durable trace is written to the database
when the run reaches a terminal state or pauses for approval.

Known limitation: a process restart mid-run loses that run's trace and its resume
context. Making runs durable across restarts needs a real worker and a shared
checkpointer — worth doing when runs are long enough to matter, not before.
"""

from __future__ import annotations

import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from agent.prompts import PROMPT_VERSION
from agent.providers import build_provider
from agent.runner import RunHandle, Runner
from agent.state import Issue
from apps.api.app.db import session_scope
from apps.api.app.events import bus
from apps.api.app.models import AgentRun, AgentStep, Approval, Repository, ToolCall
from core.config import get_settings
from guardrails.policy import RiskMode
from sandbox.local import LocalWorkspaceExecutor
from tools import repository as repo_tools
from tools import testing as testing_tools
from tools.context import ToolContext

_runner: Runner | None = None
_runner_lock = threading.Lock()


def get_runner() -> Runner:
    """One Runner per process: `resume` needs the same in-memory context that the
    interrupted run created."""
    global _runner
    with _runner_lock:
        if _runner is None:
            settings = get_settings()
            _runner = Runner(settings, lambda: build_provider(settings))
        return _runner


def reset_runner() -> None:
    """Drop the cached Runner so a new configuration takes effect. Tests only."""
    global _runner
    with _runner_lock:
        _runner = None


def register_repository(session: Session, name: str, source_path: str) -> Repository:
    path = Path(source_path).expanduser().resolve()
    if not path.is_dir():
        raise ValueError(f"not a directory: {path}")

    executor = LocalWorkspaceExecutor(path)
    ctx = ToolContext(executor=executor)
    tree = repo_tools.get_repository_tree(ctx, max_depth=3)
    framework = testing_tools.detect_test_framework(ctx)["framework"]

    repository = Repository(
        name=name,
        source_path=str(path),
        file_count=tree["file_count"],
        test_framework=framework,
        language=_detect_language(path),
    )
    session.add(repository)
    session.flush()
    return repository


def _detect_language(path: Path) -> str:
    if (path / "pyproject.toml").exists() or any(path.glob("**/*.py")):
        return "python"
    if (path / "package.json").exists():
        return "typescript"
    return "unknown"


def create_run(session: Session, payload: dict[str, Any]) -> AgentRun:
    repository = session.get(Repository, payload["repository_id"])
    if repository is None:
        raise ValueError("repository not found")

    run = AgentRun(
        repository_id=repository.id,
        issue_title=payload["issue_title"],
        issue_body=payload["issue_body"],
        repro_steps=payload.get("repro_steps"),
        expected_behavior=payload.get("expected_behavior"),
        risk_mode=payload.get("risk_mode", "standard"),
        status="queued",
        demo_mode=get_settings().provider == "fake",
        prompt_version=PROMPT_VERSION,
        model_config_json={
            "provider": get_settings().provider,
            "investigator": get_settings().investigator_model,
            "reviewer": get_settings().reviewer_model,
        },
    )
    session.add(run)
    session.flush()
    return run


def start_run_in_background(run_id: str, source_path: str) -> None:
    thread = threading.Thread(target=_execute, args=(run_id, source_path), daemon=True)
    thread.start()


def _execute(run_id: str, source_path: str) -> None:
    started = time.monotonic()
    bus.reset(run_id)

    with session_scope() as session:
        run = session.get(AgentRun, run_id)
        if run is None:
            return
        issue = Issue(
            title=run.issue_title,
            body=run.issue_body,
            repro_steps=run.repro_steps,
            expected_behavior=run.expected_behavior,
        )
        risk_mode = RiskMode(run.risk_mode)
        run.status = "running"

    bus.emit(run_id, {"type": "status", "status": "running"})

    try:
        handle = get_runner().start(
            source_repo=Path(source_path),
            issue=issue,
            risk_mode=risk_mode,
            run_id=run_id,
            emit=lambda event: bus.emit(run_id, event),
        )
        _persist(run_id, handle, int((time.monotonic() - started) * 1000))
    except Exception as exc:  # noqa: BLE001 - a crashed run must still be reported
        with session_scope() as session:
            run = session.get(AgentRun, run_id)
            if run:
                run.status = "failed"
                run.error = f"{type(exc).__name__}: {exc}"[:2000]
                run.latency_ms = int((time.monotonic() - started) * 1000)
                run.ended_at = datetime.now(UTC)
        bus.emit(run_id, {"type": "error", "message": str(exc)[:500]})
    finally:
        bus.emit(run_id, {"type": "done"})
        bus.finish(run_id)


def resume_run_in_background(run_id: str, approved: bool, comment: str) -> None:
    thread = threading.Thread(
        target=_resume, args=(run_id, approved, comment), daemon=True
    )
    thread.start()


def _resume(run_id: str, approved: bool, comment: str) -> None:
    started = time.monotonic()
    bus.reset(run_id)
    bus.emit(run_id, {"type": "status", "status": "resumed"})
    try:
        handle = get_runner().resume(run_id, approved=approved, comment=comment)
        _persist(run_id, handle, int((time.monotonic() - started) * 1000), additive_latency=True)
    except Exception as exc:  # noqa: BLE001
        with session_scope() as session:
            run = session.get(AgentRun, run_id)
            if run:
                run.status = "failed"
                run.error = f"{type(exc).__name__}: {exc}"[:2000]
        bus.emit(run_id, {"type": "error", "message": str(exc)[:500]})
    finally:
        bus.emit(run_id, {"type": "done"})
        bus.finish(run_id)


def _persist(
    run_id: str, handle: RunHandle, latency_ms: int, *, additive_latency: bool = False
) -> None:
    state = handle.state
    with session_scope() as session:
        run = session.get(AgentRun, run_id)
        if run is None:
            return

        run.status = "awaiting_approval" if handle.interrupted else str(state.status)
        run.current_phase = str(state.current_phase)
        run.workspace_path = state.workspace_path
        run.repo_git_sha = state.repo_git_sha
        run.root_cause = state.root_cause
        run.patch = state.patch
        run.patch_files = state.patch_files
        run.confidence = state.confidence
        run.escalation_reason = state.escalation_reason
        run.final_result = state.final_result.model_dump() if state.final_result else None
        run.reviewer_result = state.reviewer.model_dump() if state.reviewer else None
        run.reviewer_verdict = str(state.reviewer.verdict) if state.reviewer else ""
        run.test_results = state.test_results.model_dump() if state.test_results else None
        run.baseline_tests = state.baseline_tests.model_dump() if state.baseline_tests else None
        run.input_tokens = state.usage.input_tokens
        run.output_tokens = state.usage.output_tokens
        run.cost_usd = state.usage.cost_usd
        run.tool_call_count = state.usage.tool_calls
        run.duplicate_tool_calls = state.usage.duplicate_tool_calls
        run.step_count = len(state.steps)
        run.latency_ms = run.latency_ms + latency_ms if additive_latency else latency_ms
        run.failure_category = _classify_failure(state, handle)
        if not handle.interrupted:
            run.ended_at = datetime.now(UTC)

        _replace_children(session, run_id, state, handle)


def _replace_children(session: Session, run_id: str, state: Any, handle: RunHandle) -> None:
    for row in session.scalars(select(AgentStep).where(AgentStep.run_id == run_id)):
        session.delete(row)
    for row in session.scalars(select(ToolCall).where(ToolCall.run_id == run_id)):
        session.delete(row)
    session.flush()

    for step in state.steps:
        session.add(
            AgentStep(
                run_id=run_id, seq=step.seq, node=step.node, phase=step.phase,
                status=step.status, detail=step.detail[:4000], latency_ms=step.latency_ms,
            )
        )

    for record in get_runner().tool_history(run_id):
        session.add(
            ToolCall(
                run_id=run_id, seq=record.seq, tool_name=record.name,
                arguments=record.arguments, arguments_hash=record.arguments_hash,
                status=record.status, duration_ms=record.duration_ms,
                duplicate_of=record.duplicate_of,
                result_summary=_summarise(record.result),
            )
        )

    if handle.interrupted and handle.interrupt_payload:
        payload = handle.interrupt_payload
        existing = session.scalars(
            select(Approval).where(
                Approval.run_id == run_id,
                Approval.action_hash == payload.get("action_hash", ""),
                Approval.status == "pending",
            )
        ).first()
        if existing is None:
            session.add(
                Approval(
                    run_id=run_id,
                    action_hash=payload.get("action_hash", ""),
                    action_type=payload.get("tool", "modify_file"),
                    path=payload.get("path", ""),
                    reason=payload.get("reason", ""),
                    risk_level=payload.get("risk", "medium"),
                    status="pending",
                )
            )


def _summarise(result: dict[str, Any]) -> str:
    for key in ("match_count", "count", "total_lines", "passed", "created", "replaced"):
        if key in result:
            return f"{key}={result[key]}"
    if result.get("status") == "error":
        return f"error: {result.get('message', '')}"[:300]
    return str(result)[:300]


def _classify_failure(state: Any, handle: RunHandle) -> str:
    if handle.interrupted:
        return ""
    status = str(state.status)
    if status == "resolved":
        return ""
    if state.escalation_reason:
        reason = state.escalation_reason.lower()
        if "step limit" in reason or "tool call limit" in reason:
            return "MAX_STEPS"
        if "token budget" in reason:
            return "MAX_STEPS"
        if "rejected" in reason:
            return "POLICY_VIOLATION"
        if "reviewer" in reason:
            return "REVIEWER_REJECTION"
        if "revision limit" in reason:
            return "TEST_FAILURE"
    if not state.patch:
        return "BAD_PATCH"
    if state.test_results and not state.test_results.success:
        return "TEST_FAILURE"
    return "UNKNOWN"


def decide_approval(session: Session, run_id: str, approved: bool, comment: str) -> Approval:
    approval = session.scalars(
        select(Approval).where(Approval.run_id == run_id, Approval.status == "pending")
    ).first()
    if approval is None:
        raise ValueError("no pending approval for this run")
    approval.status = "approved" if approved else "rejected"
    approval.comment = comment
    approval.decided_at = datetime.now(UTC)
    return approval
