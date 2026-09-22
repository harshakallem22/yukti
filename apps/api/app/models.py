"""Persistence models.

One deliberate simplification: `model_usage` is folded
into columns on `agent_steps` rather than a separate table. We record one step per
node execution and have no query today that needs per-call granularity — a second
table would be an empty join. Split it when a question requires it.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from apps.api.app.db import Base


def _uuid() -> str:
    return uuid.uuid4().hex


def _now() -> datetime:
    return datetime.now(UTC)


class Repository(Base):
    __tablename__ = "repositories"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(200))
    source_path: Mapped[str] = mapped_column(Text)
    language: Mapped[str] = mapped_column(String(50), default="")
    test_framework: Mapped[str] = mapped_column(String(50), default="")
    default_branch: Mapped[str] = mapped_column(String(100), default="main")
    file_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    runs: Mapped[list[AgentRun]] = relationship(back_populates="repository")


class AgentRun(Base):
    __tablename__ = "agent_runs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    repository_id: Mapped[str] = mapped_column(ForeignKey("repositories.id"))

    issue_title: Mapped[str] = mapped_column(Text)
    issue_body: Mapped[str] = mapped_column(Text)
    repro_steps: Mapped[str | None] = mapped_column(Text, nullable=True)
    expected_behavior: Mapped[str | None] = mapped_column(Text, nullable=True)

    risk_mode: Mapped[str] = mapped_column(String(20), default="standard")
    status: Mapped[str] = mapped_column(String(30), default="queued", index=True)
    current_phase: Mapped[str] = mapped_column(String(40), default="load_context")

    workspace_path: Mapped[str] = mapped_column(Text, default="")
    repo_git_sha: Mapped[str] = mapped_column(String(64), default="")

    # Reproducibility: which model and which prompt version produced this result.
    model_config_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    prompt_version: Mapped[str] = mapped_column(String(20), default="v1")
    # True when the run used the scripted test double rather than a real model.
    # Surfaced in the UI and refused by the eval harness.
    demo_mode: Mapped[bool] = mapped_column(Boolean, default=False)

    root_cause: Mapped[str] = mapped_column(Text, default="")
    patch: Mapped[str] = mapped_column(Text, default="")
    patch_files: Mapped[list[str]] = mapped_column(JSON, default=list)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    final_result: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    reviewer_verdict: Mapped[str] = mapped_column(String(30), default="")
    reviewer_result: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    test_results: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    baseline_tests: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    escalation_reason: Mapped[str] = mapped_column(Text, default="")
    failure_category: Mapped[str] = mapped_column(String(40), default="")
    error: Mapped[str] = mapped_column(Text, default="")

    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    tool_call_count: Mapped[int] = mapped_column(Integer, default=0)
    duplicate_tool_calls: Mapped[int] = mapped_column(Integer, default=0)
    step_count: Mapped[int] = mapped_column(Integer, default=0)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, index=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    repository: Mapped[Repository] = relationship(back_populates="runs")
    steps: Mapped[list[AgentStep]] = relationship(
        back_populates="run", cascade="all, delete-orphan", order_by="AgentStep.seq"
    )
    tool_calls: Mapped[list[ToolCall]] = relationship(
        back_populates="run", cascade="all, delete-orphan", order_by="ToolCall.seq"
    )
    approvals: Mapped[list[Approval]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )


class AgentStep(Base):
    __tablename__ = "agent_steps"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    run_id: Mapped[str] = mapped_column(ForeignKey("agent_runs.id"), index=True)
    seq: Mapped[int] = mapped_column(Integer)
    node: Mapped[str] = mapped_column(String(50))
    phase: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(20))
    detail: Mapped[str] = mapped_column(Text, default="")
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    run: Mapped[AgentRun] = relationship(back_populates="steps")


class ToolCall(Base):
    __tablename__ = "tool_calls"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    run_id: Mapped[str] = mapped_column(ForeignKey("agent_runs.id"), index=True)
    seq: Mapped[int] = mapped_column(Integer)
    tool_name: Mapped[str] = mapped_column(String(50))
    arguments: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    arguments_hash: Mapped[str] = mapped_column(String(32), index=True)
    status: Mapped[str] = mapped_column(String(20))
    result_summary: Mapped[str] = mapped_column(Text, default="")
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    duplicate_of: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    run: Mapped[AgentRun] = relationship(back_populates="tool_calls")


class Approval(Base):
    __tablename__ = "approvals"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    run_id: Mapped[str] = mapped_column(ForeignKey("agent_runs.id"), index=True)
    action_hash: Mapped[str] = mapped_column(String(64))
    action_type: Mapped[str] = mapped_column(String(40))
    path: Mapped[str] = mapped_column(Text, default="")
    reason: Mapped[str] = mapped_column(Text)
    risk_level: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20), default="pending")
    comment: Mapped[str] = mapped_column(Text, default="")
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    run: Mapped[AgentRun] = relationship(back_populates="approvals")


class EvaluationRun(Base):
    __tablename__ = "evaluation_runs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    suite: Mapped[str] = mapped_column(String(80), index=True)
    git_sha: Mapped[str] = mapped_column(String(64), default="")
    model: Mapped[str] = mapped_column(String(60), default="")
    prompt_version: Mapped[str] = mapped_column(String(20), default="v1")
    baseline_run_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    aggregate_metrics: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    case_count: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, index=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    results: Mapped[list[EvaluationResult]] = relationship(
        back_populates="evaluation_run", cascade="all, delete-orphan"
    )


class EvaluationResult(Base):
    __tablename__ = "evaluation_results"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    evaluation_run_id: Mapped[str] = mapped_column(ForeignKey("evaluation_runs.id"), index=True)
    case_id: Mapped[str] = mapped_column(String(80))
    case_hash: Mapped[str] = mapped_column(String(64), default="")
    agent_run_id: Mapped[str | None] = mapped_column(String(32), nullable=True)

    task_success: Mapped[bool] = mapped_column(Boolean, default=False)
    test_pass_rate: Mapped[float] = mapped_column(Float, default=0.0)
    patch_correctness: Mapped[bool] = mapped_column(Boolean, default=False)
    regression_safety: Mapped[bool] = mapped_column(Boolean, default=False)
    file_localization_precision: Mapped[float] = mapped_column(Float, default=0.0)
    file_localization_recall: Mapped[float] = mapped_column(Float, default=0.0)
    policy_compliance: Mapped[bool] = mapped_column(Boolean, default=True)
    approval_compliance: Mapped[bool] = mapped_column(Boolean, default=True)

    steps: Mapped[int] = mapped_column(Integer, default=0)
    tool_calls: Mapped[int] = mapped_column(Integer, default=0)
    duplicate_tool_calls: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    failure_category: Mapped[str] = mapped_column(String(40), default="")
    evaluator_details: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    evaluation_run: Mapped[EvaluationRun] = relationship(back_populates="results")
