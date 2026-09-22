"""AgentState — the durable, typed state threaded through the graph.

Deliberately not a message transcript. Each node builds its prompt from the fields
it needs, so token cost does not grow linearly with step count and every routing
decision is a pure function of inspectable state.
"""

from __future__ import annotations

import operator
from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, Field

from agent.schemas import (
    FinalResult,
    Hypothesis,
    InvestigationPlan,
    IssueSummary,
    ProposedChange,
    ReviewerResult,
)
from guardrails.policy import RiskMode


class Phase(StrEnum):
    LOAD_CONTEXT = "load_context"
    UNDERSTAND_ISSUE = "understand_issue"
    CREATE_PLAN = "create_plan"
    INVESTIGATE = "investigate"
    FORM_HYPOTHESIS = "form_hypothesis"
    PROPOSE_SOLUTION = "propose_solution"
    AWAIT_APPROVAL = "await_approval"
    APPLY_PATCH = "apply_patch"
    RUN_TESTS = "run_tests"
    ANALYZE_FAILURE = "analyze_failure"
    REVISE = "revise_solution"
    REVIEW = "review_solution"
    FINALIZE = "finalize"
    ESCALATE = "escalate"


class RunStatus(StrEnum):
    RUNNING = "running"
    AWAITING_APPROVAL = "awaiting_approval"
    RESOLVED = "resolved"
    PARTIAL = "partial"
    FAILED = "failed"
    ESCALATED = "escalated"


class Issue(BaseModel):
    title: str
    body: str
    repro_steps: str | None = None
    expected_behavior: str | None = None


class RunLimits(BaseModel):
    """Frozen for the life of the run: a node that could raise its own budget is
    not a budget."""

    model_config = {"frozen": True}

    max_steps: int = 40
    max_tool_calls: int = 60
    max_revisions: int = 3
    max_tokens: int = 400_000
    max_wallclock_seconds: int = 900


class Usage(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    model_calls: int = 0
    tool_calls: int = 0
    duplicate_tool_calls: int = 0
    steps: int = 0


class TestSummary(BaseModel):
    framework: str
    command: list[str]
    passed: int
    failed: int
    errors: int
    skipped: int
    tests_executed: int
    success: bool
    output_tail: str
    duration_ms: int


class ApprovalRequest(BaseModel):
    action_hash: str
    tool: str
    path: str
    reason: str
    risk: str


class AgentError(BaseModel):
    phase: str
    type: str
    message: str
    retryable: bool


class StepRecord(BaseModel):
    """One graph node execution — the spine of the trace."""

    seq: int
    node: str
    phase: str
    status: str
    detail: str = ""
    latency_ms: int = 0


class AgentState(BaseModel):
    # --- identity and config (set once) ---
    run_id: str
    workspace_path: str
    repo_git_sha: str = ""
    risk_mode: RiskMode = RiskMode.STANDARD
    limits: RunLimits = Field(default_factory=RunLimits)

    # --- issue ---
    issue: Issue
    issue_summary: IssueSummary | None = None

    # --- planning ---
    plan: InvestigationPlan | None = None
    current_phase: Phase = Phase.LOAD_CONTEXT
    status: RunStatus = RunStatus.RUNNING

    # --- investigation (append-only audit trail) ---
    repository_map: str = ""
    files_examined: Annotated[list[str], operator.add] = Field(default_factory=list)
    hypotheses: Annotated[list[Hypothesis], operator.add] = Field(default_factory=list)

    # --- solution ---
    root_cause: str = ""
    proposed_changes: list[ProposedChange] = Field(default_factory=list)
    patch: str = ""
    patch_files: list[str] = Field(default_factory=list)
    revision_count: int = 0

    # --- validation ---
    baseline_tests: TestSummary | None = None
    test_results: TestSummary | None = None
    reviewer: ReviewerResult | None = None
    failure_analysis: str = ""

    # --- control ---
    pending_approval: ApprovalRequest | None = None
    approved_hashes: Annotated[list[str], operator.add] = Field(default_factory=list)
    errors: Annotated[list[AgentError], operator.add] = Field(default_factory=list)
    steps: Annotated[list[StepRecord], operator.add] = Field(default_factory=list)

    # --- accounting ---
    usage: Usage = Field(default_factory=Usage)
    confidence: float = 0.0
    final_result: FinalResult | None = None
    escalation_reason: str = ""

    def budget_exhausted(self) -> str | None:
        """Which hard limit, if any, has been hit. Pure function of state."""
        if self.usage.steps >= self.limits.max_steps:
            return f"step limit reached ({self.limits.max_steps})"
        if self.usage.tool_calls >= self.limits.max_tool_calls:
            return f"tool call limit reached ({self.limits.max_tool_calls})"
        if self.usage.input_tokens + self.usage.output_tokens >= self.limits.max_tokens:
            return f"token budget exhausted ({self.limits.max_tokens})"
        return None


def compute_confidence(state: AgentState) -> float:
    """Heuristic confidence from observable signals — never the model's self-report.

    Documented as a heuristic, not a calibrated probability: calibrating it would
    require plotting predicted confidence against measured eval task success.
    """
    score = 0.0
    if state.test_results and state.test_results.success:
        score += 0.35
    if state.test_results and state.test_results.tests_executed > 0:
        score += 0.05
    # No previously-passing test broke.
    if (
        state.baseline_tests
        and state.test_results
        and state.test_results.passed >= state.baseline_tests.passed
    ):
        score += 0.15
    if state.reviewer:
        if state.reviewer.verdict == "APPROVE":
            score += 0.25
        score += 0.10 * state.reviewer.correctness_score
        # An approval carrying unresolved concerns is not an unqualified approval.
        # Without this, a reviewer saying "looks right, but no regression test
        # covers it" still produced a near-1.0 score.
        score -= 0.05 * len(state.reviewer.concerns)
        score -= 0.05 * len(state.reviewer.missing_tests)
        score -= 0.10 * len(state.reviewer.security_concerns)
    if state.hypotheses:
        current = state.hypotheses[-1]
        if current.supporting_evidence:
            score += 0.10
        if current.contradicting_evidence:
            score -= 0.10
    if state.revision_count > 1:
        score -= 0.05 * (state.revision_count - 1)
    return round(max(0.0, min(1.0, score)), 2)
