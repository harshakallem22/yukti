"""Graph nodes.

Each node: build a prompt from typed state, call the model or a tool, validate,
return a partial state update. Control flow lives in graph.py; security lives in
guardrails/. Nodes stay thin so they are readable and testable.
"""

from __future__ import annotations

import json
import time
from typing import Any

from langchain_core.runnables import RunnableConfig
from langgraph.types import interrupt

from agent.prompts import load_prompt
from agent.runtime import RunContext, context_from_config
from agent.schemas import (
    FailureAnalysis,
    FinalResult,
    Hypothesis,
    InvestigationPlan,
    IssueSummary,
    ReviewerResult,
    SolutionProposal,
    Verdict,
)
from agent.state import (
    AgentError,
    AgentState,
    ApprovalRequest,
    Phase,
    RunStatus,
    StepRecord,
    TestSummary,
    compute_confidence,
)
from core.errors import ApprovalRequired, YuktiError
from guardrails.mutations import classify_patch
from guardrails.policy import ActionClass, approval_hash
from tools import git, repository, testing
from tools.registry import openai_tool_schemas

MAX_INVESTIGATION_TURNS = 12
MAX_EDIT_TURNS = 8

INVESTIGATION_TOOLS = [
    "get_repository_tree", "list_directory", "read_file", "search_code", "find_files",
]
EDIT_TOOLS = ["read_file", "replace_in_file", "write_file"]


def _step(
    state: AgentState, node: str, phase: Phase, status: str, detail: str, ms: int
) -> StepRecord:
    return StepRecord(
        seq=len(state.steps), node=node, phase=phase, status=status, detail=detail, latency_ms=ms
    )


def _emit(ctx: RunContext, node: str, status: str, detail: str = "") -> None:
    ctx.emit({"type": "step", "node": node, "status": status, "detail": detail})


# --------------------------------------------------------------------------- #
# Context and understanding
# --------------------------------------------------------------------------- #


def load_context(state: AgentState, config: RunnableConfig) -> dict[str, Any]:
    ctx = context_from_config(config)
    started = time.monotonic()
    _emit(ctx, "load_context", "running", "reading repository")

    tree = repository.get_repository_tree(ctx.invoker.ctx, max_depth=3)

    # Baseline run: without it, "this test fails" cannot be distinguished from
    # "this test was already failing", and regression safety is unmeasurable.
    baseline: TestSummary | None = None
    try:
        result = testing.run_tests(ctx.invoker.ctx)
        baseline = TestSummary(**{k: result[k] for k in TestSummary.model_fields})
    except YuktiError:
        baseline = None

    ms = int((time.monotonic() - started) * 1000)
    detail = f"{tree['file_count']} files"
    if baseline:
        detail += f", baseline {baseline.passed} passed / {baseline.failed} failed"
    _emit(ctx, "load_context", "ok", detail)

    return {
        "repository_map": tree["tree"],
        "baseline_tests": baseline,
        "current_phase": Phase.UNDERSTAND_ISSUE,
        "usage": ctx.usage(state.usage.steps + 1),
        "steps": [_step(state, "load_context", Phase.LOAD_CONTEXT, "ok", detail, ms)],
    }


def understand_issue(state: AgentState, config: RunnableConfig) -> dict[str, Any]:
    ctx = context_from_config(config)
    started = time.monotonic()
    _emit(ctx, "understand_issue", "running")

    issue = state.issue
    user = f"Title: {issue.title}\n\nDescription:\n{issue.body}"
    if issue.repro_steps:
        user += f"\n\nReproduction steps:\n{issue.repro_steps}"
    if issue.expected_behavior:
        user += f"\n\nExpected behaviour:\n{issue.expected_behavior}"

    response = ctx.provider.generate_structured(
        system=load_prompt("issue"),
        user=user,
        schema=IssueSummary,
        model=ctx.investigator_model,
    )
    ctx.record_usage(response.input_tokens, response.output_tokens, response.cost_usd)

    ms = int((time.monotonic() - started) * 1000)
    _emit(ctx, "understand_issue", "ok", response.value.summary)
    return {
        "issue_summary": response.value,
        "current_phase": Phase.CREATE_PLAN,
        "usage": ctx.usage(state.usage.steps + 1),
        "steps": [
            _step(state, "understand_issue", Phase.UNDERSTAND_ISSUE, "ok",
                  response.value.summary, ms)
        ],
    }


def create_plan(state: AgentState, config: RunnableConfig) -> dict[str, Any]:
    ctx = context_from_config(config)
    started = time.monotonic()
    _emit(ctx, "create_plan", "running")

    summary = state.issue_summary
    user = (
        f"Issue: {summary.summary if summary else state.issue.title}\n"
        f"Observed: {summary.observed_behavior if summary else ''}\n"
        f"Expected: {summary.expected_behavior if summary else ''}\n"
        f"Keywords: {', '.join(summary.search_keywords) if summary else ''}\n\n"
        f"Repository map:\n{state.repository_map[:4000]}"
    )
    response = ctx.provider.generate_structured(
        system=load_prompt("planner"), user=user, schema=InvestigationPlan,
        model=ctx.investigator_model,
    )
    ctx.record_usage(response.input_tokens, response.output_tokens, response.cost_usd)

    plan = response.value
    ms = int((time.monotonic() - started) * 1000)
    _emit(ctx, "create_plan", "ok", f"{len(plan.steps)} steps")

    # Seed the investigation transcript once; the loop appends to it thereafter.
    ctx.messages = [
        {
            "role": "user",
            "content": (
                f"# Issue\n{state.issue.title}\n\n{state.issue.body}\n\n"
                f"# Plan\nObjective: {plan.objective}\n"
                + "\n".join(f"- {s}" for s in plan.steps)
                + f"\n\n# Suggested first files\n{', '.join(plan.initial_files_to_inspect)}"
                + f"\n\n# Repository map\n{state.repository_map[:4000]}\n\n"
                "Begin the investigation using tools."
            ),
        }
    ]

    return {
        "plan": plan,
        "current_phase": Phase.INVESTIGATE,
        "usage": ctx.usage(state.usage.steps + 1),
        "steps": [_step(state, "create_plan", Phase.CREATE_PLAN, "ok", plan.objective, ms)],
    }


# --------------------------------------------------------------------------- #
# Investigation loop
# --------------------------------------------------------------------------- #


def investigate(state: AgentState, config: RunnableConfig) -> dict[str, Any]:
    """One turn: model decides, tools execute, observations recorded.

    A graph cycle rather than an in-node while-loop, so every tool call is its own
    checkpoint and its own row in the trace.
    """
    ctx = context_from_config(config)
    started = time.monotonic()

    response = ctx.provider.generate(
        system=load_prompt("investigator"),
        messages=ctx.messages,
        tools=openai_tool_schemas(INVESTIGATION_TOOLS),
        model=ctx.investigator_model,
    )
    ctx.record_usage(response.input_tokens, response.output_tokens, response.cost_usd)

    if not response.tool_calls:
        ms = int((time.monotonic() - started) * 1000)
        _emit(ctx, "investigate", "ok", "investigation complete")
        ctx.messages.append({"role": "assistant", "content": response.text})
        return {
            "current_phase": Phase.FORM_HYPOTHESIS,
            "files_examined": _new_files(state, ctx),
            "usage": ctx.usage(state.usage.steps + 1),
            "steps": [
                _step(state, "investigate", Phase.INVESTIGATE, "ok",
                      response.text[:300] or "no further tools needed", ms)
            ],
        }

    ctx.messages.append(
        {
            "role": "assistant",
            "content": response.text or None,
            "tool_calls": [
                {
                    "id": c.id,
                    "type": "function",
                    "function": {"name": c.name, "arguments": json.dumps(c.arguments)},
                }
                for c in response.tool_calls
            ],
        }
    )

    details = []
    for call in response.tool_calls:
        _emit(ctx, "tool", "running", f"{call.name}({_brief(call.arguments)})")
        try:
            result = ctx.invoker.invoke(call.name, call.arguments)
        except YuktiError as exc:
            result = exc.to_observation()
        ctx.messages.append(
            {
                "role": "tool",
                "tool_call_id": call.id,
                "content": json.dumps(result, default=str)[:6000],
            }
        )
        details.append(f"{call.name}({_brief(call.arguments)})")
        _emit(ctx, "tool", "ok", details[-1])

    ms = int((time.monotonic() - started) * 1000)
    return {
        "files_examined": _new_files(state, ctx),
        "usage": ctx.usage(state.usage.steps + 1),
        "steps": [
            _step(state, "investigate", Phase.INVESTIGATE, "ok", "; ".join(details), ms)
        ],
    }


def _test_line(tests: TestSummary | None) -> str:
    if tests is None:
        return "tests did not run"
    return (
        f"{tests.passed} passed, {tests.failed} failed, {tests.errors} errors, "
        f"{tests.tests_executed} executed"
    )


def _brief(arguments: dict[str, Any]) -> str:
    for key in ("path", "query", "pattern", "target"):
        if key in arguments:
            return str(arguments[key])[:60]
    return ""


def _new_files(state: AgentState, ctx: RunContext) -> list[str]:
    known = set(state.files_examined)
    return [p for p in ctx.invoker.files_examined() if p not in known]


def form_hypothesis(state: AgentState, config: RunnableConfig) -> dict[str, Any]:
    ctx = context_from_config(config)
    started = time.monotonic()
    _emit(ctx, "form_hypothesis", "running")

    findings = _transcript_digest(ctx)
    response = ctx.provider.generate_structured(
        system=load_prompt("hypothesis"),
        user=f"# Issue\n{state.issue.title}\n{state.issue.body}\n\n"
        f"# Investigation findings\n{findings}",
        schema=Hypothesis,
        model=ctx.investigator_model,
    )
    ctx.record_usage(response.input_tokens, response.output_tokens, response.cost_usd)

    hypothesis = response.value
    ms = int((time.monotonic() - started) * 1000)
    _emit(ctx, "form_hypothesis", "ok", hypothesis.description[:200])
    return {
        "hypotheses": [hypothesis],
        "root_cause": hypothesis.description,
        "current_phase": Phase.PROPOSE_SOLUTION,
        "usage": ctx.usage(state.usage.steps + 1),
        "steps": [
            _step(state, "form_hypothesis", Phase.FORM_HYPOTHESIS, "ok",
                  hypothesis.description[:300], ms)
        ],
    }


def _transcript_digest(ctx: RunContext, limit: int = 12000) -> str:
    """Compact the tool transcript for a single structured call.

    Tool results are truncated per message rather than passing the raw buffer:
    the hypothesis node needs what was found, not every byte that was read.
    """
    parts = []
    for message in ctx.messages:
        if message["role"] == "assistant" and message.get("content"):
            parts.append(f"Reasoning: {message['content']}")
        elif message["role"] == "tool":
            parts.append(f"Observation: {message['content'][:1200]}")
    digest = "\n\n".join(parts)
    return digest[-limit:]


# --------------------------------------------------------------------------- #
# Solution, risk, approval
# --------------------------------------------------------------------------- #


def propose_solution(state: AgentState, config: RunnableConfig) -> dict[str, Any]:
    ctx = context_from_config(config)
    started = time.monotonic()
    _emit(ctx, "propose_solution", "running")

    hypothesis = state.hypotheses[-1] if state.hypotheses else None
    evidence = ""
    if hypothesis:
        evidence = "\n".join(
            f"- {e.file_path}:{e.line_start}-{e.line_end}: {e.claim}\n  {e.excerpt[:300]}"
            for e in hypothesis.supporting_evidence
        )

    user = (
        f"# Issue\n{state.issue.title}\n{state.issue.body}\n\n"
        f"# Root cause\n{state.root_cause}\n\n"
        f"# Evidence\n{evidence}\n\n"
        f"# Files examined\n{', '.join(state.files_examined)}"
    )
    if state.failure_analysis:
        user += f"\n\n# Previous attempt failed\n{state.failure_analysis}"

    response = ctx.provider.generate_structured(
        system=load_prompt("solution"), user=user, schema=SolutionProposal,
        model=ctx.investigator_model,
    )
    ctx.record_usage(response.input_tokens, response.output_tokens, response.cost_usd)

    proposal = response.value
    ms = int((time.monotonic() - started) * 1000)
    _emit(ctx, "propose_solution", "ok", f"{len(proposal.changes)} file(s)")
    return {
        "proposed_changes": proposal.changes,
        "root_cause": proposal.root_cause or state.root_cause,
        "current_phase": Phase.APPLY_PATCH,
        "usage": ctx.usage(state.usage.steps + 1),
        "steps": [
            _step(state, "propose_solution", Phase.PROPOSE_SOLUTION, "ok",
                  "; ".join(c.file_path for c in proposal.changes), ms)
        ],
    }


def risk_check(state: AgentState, config: RunnableConfig) -> dict[str, Any]:
    """Deterministic. No LLM decides whether a change needs human approval."""
    ctx = context_from_config(config)
    paths = [c.file_path for c in state.proposed_changes]
    decision = classify_patch(paths, lines_changed=0, risk_mode=state.risk_mode)

    if decision.action_class is ActionClass.SAFE:
        _emit(ctx, "risk_check", "ok", "no approval required")
        return {
            "current_phase": Phase.APPLY_PATCH,
            "steps": [_step(state, "risk_check", Phase.APPLY_PATCH, "ok", decision.reason, 0)],
        }

    sensitive = next(
        (p for p in paths if classify_patch([p], 0).action_class is not ActionClass.SAFE),
        paths[0] if paths else "",
    )
    request = ApprovalRequest(
        action_hash=approval_hash(sensitive, decision.reason),
        tool="modify_file",
        path=sensitive,
        reason=decision.reason,
        risk=str(decision.risk),
    )
    _emit(ctx, "risk_check", "awaiting_approval", decision.reason)
    return {
        "pending_approval": request,
        "status": RunStatus.AWAITING_APPROVAL,
        "current_phase": Phase.AWAIT_APPROVAL,
        "steps": [
            _step(state, "risk_check", Phase.AWAIT_APPROVAL, "awaiting_approval",
                  decision.reason, 0)
        ],
    }


def human_approval(state: AgentState, config: RunnableConfig) -> dict[str, Any]:
    """Pause the run. LangGraph checkpoints here; the process is free to exit."""
    ctx = context_from_config(config)
    request = state.pending_approval
    payload = request.model_dump() if request else {}
    _emit(ctx, "human_approval", "awaiting_approval", request.reason if request else "")

    decision = interrupt({"kind": "approval_request", **payload})

    approved = bool(decision.get("approved")) if isinstance(decision, dict) else bool(decision)
    comment = decision.get("comment", "") if isinstance(decision, dict) else ""

    if not approved:
        return {
            "pending_approval": None,
            "status": RunStatus.ESCALATED,
            "current_phase": Phase.ESCALATE,
            "escalation_reason": f"human rejected the required approval. {comment}".strip(),
            "steps": [
                _step(state, "human_approval", Phase.AWAIT_APPROVAL, "rejected", comment, 0)
            ],
        }

    # The invoker only honours hashes granted here, and the hash covers this exact
    # file and rule — a later action against a different file is not authorised.
    granted = request.action_hash if request else ""
    ctx.invoker.approved_hashes.add(granted)
    return {
        "pending_approval": None,
        "approved_hashes": [granted],
        "status": RunStatus.RUNNING,
        "current_phase": Phase.APPLY_PATCH,
        "steps": [_step(state, "human_approval", Phase.AWAIT_APPROVAL, "approved", comment, 0)],
    }


# --------------------------------------------------------------------------- #
# Editing and validation
# --------------------------------------------------------------------------- #


def apply_patch(state: AgentState, config: RunnableConfig) -> dict[str, Any]:
    ctx = context_from_config(config)
    started = time.monotonic()
    _emit(ctx, "apply_patch", "running")

    plan_text = "\n".join(
        f"- {c.file_path}: {c.change_description} (reason: {c.reason})"
        for c in state.proposed_changes
    )
    messages: list[dict[str, Any]] = [
        {
            "role": "user",
            "content": f"# Approved changes\n{plan_text}\n\n"
            f"# Root cause\n{state.root_cause}\n\nApply these changes now.",
        }
    ]

    errors: list[AgentError] = []
    for _ in range(MAX_EDIT_TURNS):
        response = ctx.provider.generate(
            system=load_prompt("editor"),
            messages=messages,
            tools=openai_tool_schemas(EDIT_TOOLS),
            model=ctx.investigator_model,
        )
        ctx.record_usage(response.input_tokens, response.output_tokens, response.cost_usd)

        if not response.tool_calls:
            break

        messages.append(
            {
                "role": "assistant",
                "content": response.text or None,
                "tool_calls": [
                    {
                        "id": c.id,
                        "type": "function",
                        "function": {"name": c.name, "arguments": json.dumps(c.arguments)},
                    }
                    for c in response.tool_calls
                ],
            }
        )
        for call in response.tool_calls:
            _emit(ctx, "tool", "running", f"{call.name}({_brief(call.arguments)})")
            try:
                result = ctx.invoker.invoke(call.name, call.arguments)
            except ApprovalRequired as exc:
                # Reached only if the editor targets a sensitive file the risk
                # check did not anticipate. Refused, not silently allowed.
                result = exc.to_observation()
                errors.append(
                    AgentError(
                        phase="apply_patch", type="approval_required",
                        message=exc.message, retryable=False,
                    )
                )
            except YuktiError as exc:
                result = exc.to_observation()
            messages.append(
                {"role": "tool", "tool_call_id": call.id,
                 "content": json.dumps(result, default=str)[:3000]}
            )

    diff = git.git_diff(ctx.invoker.ctx)
    ms = int((time.monotonic() - started) * 1000)
    detail = (
        f"{len(diff['files_changed'])} file(s), +{diff['lines_added']}/-{diff['lines_removed']}"
        if not diff["is_empty"]
        else "no changes produced"
    )
    _emit(ctx, "apply_patch", "ok" if not diff["is_empty"] else "error", detail)

    return {
        "patch": diff["diff"],
        "patch_files": diff["files_changed"],
        "current_phase": Phase.RUN_TESTS,
        "errors": errors,
        "usage": ctx.usage(state.usage.steps + 1),
        "steps": [_step(state, "apply_patch", Phase.APPLY_PATCH, "ok", detail, ms)],
    }


def run_tests(state: AgentState, config: RunnableConfig) -> dict[str, Any]:
    ctx = context_from_config(config)
    started = time.monotonic()
    _emit(ctx, "run_tests", "running")

    try:
        result = testing.run_tests(ctx.invoker.ctx)
        summary = TestSummary(**{k: result[k] for k in TestSummary.model_fields})
        status, detail = "ok", f"{summary.passed} passed, {summary.failed} failed"
    except YuktiError as exc:
        summary = None
        status, detail = "error", exc.message

    ms = int((time.monotonic() - started) * 1000)
    _emit(ctx, "run_tests", status, detail)
    return {
        "test_results": summary,
        "current_phase": Phase.REVIEW if summary and summary.success else Phase.ANALYZE_FAILURE,
        "usage": ctx.usage(state.usage.steps + 1),
        "steps": [_step(state, "run_tests", Phase.RUN_TESTS, status, detail, ms)],
    }


def analyze_failure(state: AgentState, config: RunnableConfig) -> dict[str, Any]:
    ctx = context_from_config(config)
    started = time.monotonic()
    _emit(ctx, "analyze_failure", "running")

    output = state.test_results.output_tail if state.test_results else "no output"
    user = (
        f"# Root cause\n{state.root_cause}\n\n"
        f"# Patch\n{state.patch[:4000]}\n\n"
        f"# Test output\n{output}\n\n"
        f"# Baseline before patch\n{_test_line(state.baseline_tests)}"
    )
    response = ctx.provider.generate_structured(
        system=load_prompt("failure"), user=user, schema=FailureAnalysis,
        model=ctx.investigator_model,
    )
    ctx.record_usage(response.input_tokens, response.output_tokens, response.cost_usd)

    analysis = response.value
    ms = int((time.monotonic() - started) * 1000)
    _emit(ctx, "analyze_failure", "ok", analysis.diagnosis[:200])
    return {
        "failure_analysis": f"{analysis.diagnosis}\nNext: {analysis.next_action}",
        "revision_count": state.revision_count + 1,
        "current_phase": Phase.REVISE,
        "usage": ctx.usage(state.usage.steps + 1),
        "steps": [
            _step(state, "analyze_failure", Phase.ANALYZE_FAILURE,
                  "ok" if analysis.should_retry else "exhausted", analysis.diagnosis[:300], ms)
        ],
    }


def review_solution(state: AgentState, config: RunnableConfig) -> dict[str, Any]:
    """Independent review.

    The reviewer receives the issue, the diff and the test results — deliberately
    NOT the investigator's reasoning. A reviewer shown the argument tends to
    ratify it; one shown only the artifact has to form its own view.
    """
    ctx = context_from_config(config)
    started = time.monotonic()
    _emit(ctx, "review_solution", "running")

    tests = state.test_results
    user = (
        f"# Reported issue\n{state.issue.title}\n\n{state.issue.body}\n\n"
        f"# Diff under review\n```diff\n{state.patch[:8000]}\n```\n\n"
        f"# Test results\n{_test_line(tests)}\n\n"
        f"# Test output\n{tests.output_tail[-3000:] if tests else ''}"
    )
    response = ctx.provider.generate_structured(
        system=load_prompt("reviewer"), user=user, schema=ReviewerResult,
        model=ctx.reviewer_model,
    )
    ctx.record_usage(response.input_tokens, response.output_tokens, response.cost_usd)

    review = response.value
    ms = int((time.monotonic() - started) * 1000)
    _emit(ctx, "review_solution", "ok", f"{review.verdict} ({review.correctness_score:.2f})")

    updates: dict[str, Any] = {
        "reviewer": review,
        "usage": ctx.usage(state.usage.steps + 1),
        "steps": [
            _step(state, "review_solution", Phase.REVIEW, "ok",
                  f"{review.verdict}: {review.reasoning[:200]}", ms)
        ],
    }
    if review.verdict == Verdict.REQUEST_CHANGES:
        updates["revision_count"] = state.revision_count + 1
        updates["failure_analysis"] = "Reviewer requested changes: " + "; ".join(review.concerns)
    return updates


def finalize(state: AgentState, config: RunnableConfig) -> dict[str, Any]:
    ctx = context_from_config(config)
    started = time.monotonic()
    _emit(ctx, "finalize", "running")

    tests = state.test_results
    review = state.reviewer
    user = (
        f"# Issue\n{state.issue.title}\n{state.issue.body}\n\n"
        f"# Root cause found\n{state.root_cause}\n\n"
        f"# Files changed\n{', '.join(state.patch_files) or 'none'}\n\n"
        f"# Diff\n{state.patch[:4000]}\n\n"
        f"# Tests\n{_test_line(tests)}\n\n"
        f"# Reviewer\n{f'{review.verdict}: {review.reasoning}' if review else 'no review'}\n\n"
        f"# Escalation\n{state.escalation_reason or 'none'}"
    )
    response = ctx.provider.generate_structured(
        system=load_prompt("finalizer"), user=user, schema=FinalResult,
        model=ctx.investigator_model,
    )
    ctx.record_usage(response.input_tokens, response.output_tokens, response.cost_usd)

    confidence = compute_confidence(state)
    status = _terminal_status(state)
    ms = int((time.monotonic() - started) * 1000)
    _emit(ctx, "finalize", "ok", f"{status} (confidence {confidence})")

    return {
        "final_result": response.value,
        "confidence": confidence,
        "status": status,
        "current_phase": Phase.FINALIZE,
        "usage": ctx.usage(state.usage.steps + 1),
        "steps": [_step(state, "finalize", Phase.FINALIZE, "ok", str(status), ms)],
    }


def _terminal_status(state: AgentState) -> RunStatus:
    if state.status is RunStatus.ESCALATED or state.escalation_reason:
        return RunStatus.ESCALATED
    tests_pass = bool(state.test_results and state.test_results.success)
    approved = bool(state.reviewer and state.reviewer.verdict == Verdict.APPROVE)
    if tests_pass and approved:
        return RunStatus.RESOLVED
    if tests_pass or state.patch:
        return RunStatus.PARTIAL
    return RunStatus.FAILED


def escalate(state: AgentState, config: RunnableConfig) -> dict[str, Any]:
    ctx = context_from_config(config)
    reason = state.escalation_reason or _escalation_reason(state)
    _emit(ctx, "escalate", "escalated", reason)
    return {
        "status": RunStatus.ESCALATED,
        "escalation_reason": reason,
        "current_phase": Phase.ESCALATE,
        "steps": [_step(state, "escalate", Phase.ESCALATE, "escalated", reason, 0)],
    }


def _escalation_reason(state: AgentState) -> str:
    if budget := state.budget_exhausted():
        return budget
    if state.revision_count >= state.limits.max_revisions:
        return f"revision limit reached ({state.limits.max_revisions}) without passing tests"
    if state.reviewer and state.reviewer.verdict == Verdict.ESCALATE_TO_HUMAN:
        return f"reviewer escalated: {state.reviewer.reasoning}"
    return "unable to produce a validated fix"
