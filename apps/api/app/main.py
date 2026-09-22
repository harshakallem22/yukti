"""Yukti HTTP API."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from apps.api.app import service
from apps.api.app.db import get_session, init_db
from apps.api.app.events import bus
from apps.api.app.models import (
    AgentRun,
    AgentStep,
    Approval,
    EvaluationResult,
    EvaluationRun,
    Repository,
    ToolCall,
)
from apps.api.app.schemas import (
    ApprovalDecision,
    ApprovalOut,
    EvaluationResultOut,
    EvaluationRunOut,
    MetricsSummary,
    RepositoryCreate,
    RepositoryOut,
    RunCreate,
    RunDetail,
    RunSummary,
    StepOut,
    ToolCallOut,
)
from core.config import get_settings

settings = get_settings()

HEARTBEAT_SECONDS = 15.0
POLL_SECONDS = 0.25


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    init_db()
    yield


app = FastAPI(title="Yukti API", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)


@app.get("/api/health")
def health() -> dict[str, Any]:
    settings = get_settings()
    return {
        "status": "ok",
        "provider": settings.provider,
        "sandbox_mode": settings.sandbox_mode,
        "model_access": settings.has_model_access,
        # Surfaced so the UI can badge scripted runs; a demo must never be
        # mistakable for real agent performance.
        "demo_mode": settings.provider == "fake",
    }


# --------------------------------------------------------------------------- #
# Repositories
# --------------------------------------------------------------------------- #


@app.post("/api/repositories", response_model=RepositoryOut, status_code=201)
def create_repository(
    payload: RepositoryCreate, session: Session = Depends(get_session)
) -> Repository:
    try:
        repository = service.register_repository(session, payload.name, payload.source_path)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    session.commit()
    return repository


@app.get("/api/repositories", response_model=list[RepositoryOut])
def list_repositories(session: Session = Depends(get_session)) -> list[Repository]:
    return list(session.scalars(select(Repository).order_by(Repository.created_at.desc())))


@app.get("/api/repositories/{repository_id}", response_model=RepositoryOut)
def get_repository(repository_id: str, session: Session = Depends(get_session)) -> Repository:
    repository = session.get(Repository, repository_id)
    if repository is None:
        raise HTTPException(status_code=404, detail="repository not found")
    return repository


@app.get("/api/repositories/{repository_id}/tree")
def repository_tree(repository_id: str, session: Session = Depends(get_session)) -> dict[str, Any]:
    from pathlib import Path

    from sandbox.local import LocalWorkspaceExecutor
    from tools import repository as repo_tools
    from tools.context import ToolContext

    repository = session.get(Repository, repository_id)
    if repository is None:
        raise HTTPException(status_code=404, detail="repository not found")
    ctx = ToolContext(executor=LocalWorkspaceExecutor(Path(repository.source_path)))
    return repo_tools.get_repository_tree(ctx, max_depth=4)


# --------------------------------------------------------------------------- #
# Runs
# --------------------------------------------------------------------------- #


@app.post("/api/runs", response_model=RunSummary, status_code=201)
def create_run(payload: RunCreate, session: Session = Depends(get_session)) -> AgentRun:
    try:
        run = service.create_run(session, payload.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    repository = session.get(Repository, run.repository_id)
    source_path = repository.source_path if repository else ""
    run_id = run.id
    session.commit()

    service.start_run_in_background(run_id, source_path)
    return run


@app.get("/api/runs", response_model=list[RunSummary])
def list_runs(
    limit: int = 50, repository_id: str | None = None, session: Session = Depends(get_session)
) -> list[AgentRun]:
    query = select(AgentRun).order_by(AgentRun.created_at.desc()).limit(min(limit, 200))
    if repository_id:
        query = query.where(AgentRun.repository_id == repository_id)
    return list(session.scalars(query))


@app.get("/api/runs/{run_id}", response_model=RunDetail)
def get_run(run_id: str, session: Session = Depends(get_session)) -> AgentRun:
    run = session.get(AgentRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")
    return run


@app.get("/api/runs/{run_id}/steps", response_model=list[StepOut])
def get_run_steps(run_id: str, session: Session = Depends(get_session)) -> list[AgentStep]:
    return list(
        session.scalars(select(AgentStep).where(AgentStep.run_id == run_id).order_by(AgentStep.seq))
    )


@app.get("/api/runs/{run_id}/tool-calls", response_model=list[ToolCallOut])
def get_run_tool_calls(run_id: str, session: Session = Depends(get_session)) -> list[ToolCall]:
    return list(
        session.scalars(select(ToolCall).where(ToolCall.run_id == run_id).order_by(ToolCall.seq))
    )


@app.get("/api/runs/{run_id}/diff")
def get_run_diff(run_id: str, session: Session = Depends(get_session)) -> dict[str, Any]:
    run = session.get(AgentRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")
    return {"diff": run.patch, "files_changed": run.patch_files}


@app.get("/api/runs/{run_id}/approval", response_model=ApprovalOut | None)
def get_pending_approval(run_id: str, session: Session = Depends(get_session)) -> Approval | None:
    return session.scalars(
        select(Approval).where(Approval.run_id == run_id, Approval.status == "pending")
    ).first()


@app.post("/api/runs/{run_id}/approve", response_model=ApprovalOut)
def approve_run(
    run_id: str, decision: ApprovalDecision, session: Session = Depends(get_session)
) -> Approval:
    run = session.get(AgentRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")
    if run.status != "awaiting_approval":
        raise HTTPException(status_code=409, detail="run is not awaiting approval")
    try:
        approval = service.decide_approval(session, run_id, decision.approved, decision.comment)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    run.status = "running"
    session.commit()

    service.resume_run_in_background(run_id, decision.approved, decision.comment)
    return approval


@app.get("/api/approvals", response_model=list[ApprovalOut])
def list_pending_approvals(session: Session = Depends(get_session)) -> list[Approval]:
    return list(
        session.scalars(
            select(Approval)
            .where(Approval.status == "pending")
            .order_by(Approval.requested_at.desc())
        )
    )


@app.get("/api/runs/{run_id}/events")
async def stream_run_events(run_id: str, request: Request) -> StreamingResponse:
    """SSE stream of live run events.

    `Last-Event-ID` lets a reconnecting client replay from where it dropped rather
    than losing steps — the reason SSE was chosen over polling (ADR 003).
    """
    start_index = 0
    if last_id := request.headers.get("last-event-id"):
        try:
            start_index = int(last_id) + 1
        except ValueError:
            start_index = 0

    async def generator() -> AsyncIterator[str]:
        index = start_index
        last_beat = asyncio.get_event_loop().time()
        while True:
            if await request.is_disconnected():
                return
            for event in bus.since(run_id, index):
                index = event["seq"] + 1
                yield f"id: {event['seq']}\nevent: {event.get('type', 'message')}\n"
                yield f"data: {json.dumps(event)}\n\n"
                last_beat = asyncio.get_event_loop().time()
            if bus.is_finished(run_id) and not bus.since(run_id, index):
                yield "event: close\ndata: {}\n\n"
                return
            now = asyncio.get_event_loop().time()
            if now - last_beat > HEARTBEAT_SECONDS:
                # Comment frame keeps intermediaries from closing an idle stream
                # during a long test run.
                yield ": heartbeat\n\n"
                last_beat = now
            await asyncio.sleep(POLL_SECONDS)

    return StreamingResponse(
        generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# --------------------------------------------------------------------------- #
# Metrics and evaluations
# --------------------------------------------------------------------------- #


@app.get("/api/metrics/summary", response_model=MetricsSummary)
def metrics_summary(session: Session = Depends(get_session)) -> MetricsSummary:
    total = session.scalar(select(func.count()).select_from(AgentRun)) or 0
    terminal = ("resolved", "partial", "failed", "escalated")

    def count_status(*statuses: str) -> int:
        return (
            session.scalar(
                select(func.count()).select_from(AgentRun).where(AgentRun.status.in_(statuses))
            )
            or 0
        )

    finished = count_status(*terminal)
    resolved = count_status("resolved")
    aggregates = session.execute(
        select(
            func.avg(AgentRun.cost_usd),
            func.avg(AgentRun.latency_ms),
            func.avg(AgentRun.tool_call_count),
        ).where(AgentRun.status.in_(terminal))
    ).one()

    return MetricsSummary(
        total_runs=total,
        resolved=resolved,
        escalated=count_status("escalated"),
        failed=count_status("failed"),
        success_rate=round(resolved / finished, 4) if finished else 0.0,
        avg_cost_usd=round(aggregates[0] or 0.0, 6),
        avg_latency_ms=round(aggregates[1] or 0.0, 1),
        avg_tool_calls=round(aggregates[2] or 0.0, 2),
        pending_approvals=session.scalar(
            select(func.count()).select_from(Approval).where(Approval.status == "pending")
        )
        or 0,
        demo_runs=session.scalar(
            select(func.count()).select_from(AgentRun).where(AgentRun.demo_mode.is_(True))
        )
        or 0,
    )


@app.get("/api/evaluations", response_model=list[EvaluationRunOut])
def list_evaluations(session: Session = Depends(get_session)) -> list[EvaluationRun]:
    return list(
        session.scalars(select(EvaluationRun).order_by(EvaluationRun.started_at.desc()).limit(50))
    )


@app.get("/api/evaluations/{evaluation_id}", response_model=EvaluationRunOut)
def get_evaluation(evaluation_id: str, session: Session = Depends(get_session)) -> EvaluationRun:
    evaluation = session.get(EvaluationRun, evaluation_id)
    if evaluation is None:
        raise HTTPException(status_code=404, detail="evaluation run not found")
    return evaluation


@app.get("/api/evaluations/{evaluation_id}/results", response_model=list[EvaluationResultOut])
def get_evaluation_results(
    evaluation_id: str, session: Session = Depends(get_session)
) -> list[EvaluationResult]:
    return list(
        session.scalars(
            select(EvaluationResult).where(EvaluationResult.evaluation_run_id == evaluation_id)
        )
    )
