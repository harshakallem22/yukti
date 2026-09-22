"""API request and response models."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class RepositoryCreate(BaseModel):
    name: str
    source_path: str


class RepositoryOut(BaseModel):
    id: str
    name: str
    source_path: str
    language: str
    test_framework: str
    file_count: int
    created_at: datetime

    model_config = {"from_attributes": True}


class RunCreate(BaseModel):
    repository_id: str
    issue_title: str = Field(min_length=3)
    issue_body: str = Field(min_length=3)
    repro_steps: str | None = None
    expected_behavior: str | None = None
    risk_mode: str = "standard"


class RunSummary(BaseModel):
    id: str
    repository_id: str
    issue_title: str
    status: str
    current_phase: str
    confidence: float
    cost_usd: float
    latency_ms: int
    step_count: int
    tool_call_count: int
    reviewer_verdict: str
    demo_mode: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class StepOut(BaseModel):
    seq: int
    node: str
    phase: str
    status: str
    detail: str
    latency_ms: int

    model_config = {"from_attributes": True}


class ToolCallOut(BaseModel):
    seq: int
    tool_name: str
    arguments: dict[str, Any]
    status: str
    result_summary: str
    duration_ms: int
    duplicate_of: int | None

    model_config = {"from_attributes": True}


class ApprovalOut(BaseModel):
    id: str
    run_id: str
    action_hash: str
    action_type: str
    path: str
    reason: str
    risk_level: str
    status: str
    comment: str
    requested_at: datetime

    model_config = {"from_attributes": True}


class ApprovalDecision(BaseModel):
    approved: bool
    comment: str = ""


class RunDetail(RunSummary):
    issue_body: str
    root_cause: str
    patch: str
    patch_files: list[str]
    final_result: dict[str, Any] | None
    reviewer_result: dict[str, Any] | None
    test_results: dict[str, Any] | None
    baseline_tests: dict[str, Any] | None
    escalation_reason: str
    error: str
    input_tokens: int
    output_tokens: int
    duplicate_tool_calls: int
    workspace_path: str


class MetricsSummary(BaseModel):
    total_runs: int
    resolved: int
    escalated: int
    failed: int
    success_rate: float
    avg_cost_usd: float
    avg_latency_ms: float
    avg_tool_calls: float
    pending_approvals: int
    demo_runs: int


class EvaluationResultOut(BaseModel):
    case_id: str
    task_success: bool
    test_pass_rate: float
    patch_correctness: bool
    regression_safety: bool
    file_localization_precision: float
    file_localization_recall: float
    policy_compliance: bool
    approval_compliance: bool
    steps: int
    tool_calls: int
    duplicate_tool_calls: int
    cost_usd: float
    latency_ms: int
    failure_category: str

    model_config = {"from_attributes": True}


class EvaluationRunOut(BaseModel):
    id: str
    suite: str
    git_sha: str
    model: str
    prompt_version: str
    case_count: int
    aggregate_metrics: dict[str, Any]
    started_at: datetime
    ended_at: datetime | None

    model_config = {"from_attributes": True}
