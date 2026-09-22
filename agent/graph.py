"""The Yukti workflow graph.

Routing is deterministic: every conditional edge is a pure Python predicate over
`AgentState`. The model decides *what to investigate*; it never decides whether it
is finished, whether a budget is exhausted, or whether a change needs approval.
"""

from __future__ import annotations

from typing import Any

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from agent import nodes
from agent.schemas import Verdict
from agent.state import AgentState, Phase, RunStatus


def _investigation_complete(state: AgentState) -> str:
    """Three ways out of the investigation loop, all deterministic."""
    if state.budget_exhausted():
        return "escalate"
    if state.current_phase == Phase.FORM_HYPOTHESIS:
        return "form_hypothesis"
    turns = sum(1 for step in state.steps if step.node == "investigate")
    if turns >= nodes.MAX_INVESTIGATION_TURNS:
        return "form_hypothesis"
    return "investigate"


def _needs_approval(state: AgentState) -> str:
    return "human_approval" if state.pending_approval else "apply_patch"


def _after_approval(state: AgentState) -> str:
    return "escalate" if state.status == RunStatus.ESCALATED else "apply_patch"


def _tests_passed(state: AgentState) -> str:
    if state.budget_exhausted():
        return "escalate"
    if state.test_results and state.test_results.success:
        return "review_solution"
    return "analyze_failure"


def _retry_allowed(state: AgentState) -> str:
    """Bounded revision loop — the guard that stops an agent looping forever."""
    if state.revision_count >= state.limits.max_revisions:
        return "escalate"
    if state.budget_exhausted():
        return "escalate"
    return "propose_solution"


def _review_outcome(state: AgentState) -> str:
    if not state.reviewer:
        return "finalize"
    if state.reviewer.verdict == Verdict.APPROVE:
        return "finalize"
    if state.reviewer.verdict == Verdict.ESCALATE_TO_HUMAN:
        return "escalate"
    return _retry_allowed(state)


def build_graph(
    checkpointer: BaseCheckpointSaver[Any] | None = None,
) -> CompiledStateGraph[Any, Any, Any]:
    graph = StateGraph(AgentState)

    graph.add_node("load_context", nodes.load_context)
    graph.add_node("understand_issue", nodes.understand_issue)
    graph.add_node("create_plan", nodes.create_plan)
    graph.add_node("investigate", nodes.investigate)
    graph.add_node("form_hypothesis", nodes.form_hypothesis)
    graph.add_node("propose_solution", nodes.propose_solution)
    graph.add_node("risk_check", nodes.risk_check)
    graph.add_node("human_approval", nodes.human_approval)
    graph.add_node("apply_patch", nodes.apply_patch)
    graph.add_node("run_tests", nodes.run_tests)
    graph.add_node("analyze_failure", nodes.analyze_failure)
    graph.add_node("review_solution", nodes.review_solution)
    graph.add_node("finalize", nodes.finalize)
    graph.add_node("escalate", nodes.escalate)

    graph.add_edge(START, "load_context")
    graph.add_edge("load_context", "understand_issue")
    graph.add_edge("understand_issue", "create_plan")
    graph.add_edge("create_plan", "investigate")

    graph.add_conditional_edges(
        "investigate", _investigation_complete, ["investigate", "form_hypothesis", "escalate"]
    )
    graph.add_edge("form_hypothesis", "propose_solution")
    graph.add_edge("propose_solution", "risk_check")
    graph.add_conditional_edges("risk_check", _needs_approval, ["human_approval", "apply_patch"])
    graph.add_conditional_edges("human_approval", _after_approval, ["apply_patch", "escalate"])
    graph.add_edge("apply_patch", "run_tests")
    graph.add_conditional_edges(
        "run_tests", _tests_passed, ["review_solution", "analyze_failure", "escalate"]
    )
    graph.add_conditional_edges("analyze_failure", _retry_allowed, ["propose_solution", "escalate"])
    graph.add_conditional_edges(
        "review_solution", _review_outcome, ["finalize", "propose_solution", "escalate"]
    )
    graph.add_edge("escalate", "finalize")
    graph.add_edge("finalize", END)

    return graph.compile(checkpointer=checkpointer or InMemorySaver())
