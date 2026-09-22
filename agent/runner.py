"""Run orchestration: provision a workspace, wire the runtime, drive the graph."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.memory import InMemorySaver

from agent.graph import build_graph
from agent.providers.base import ModelProvider
from agent.runtime import RunContext
from agent.state import AgentState, Issue, RunLimits, RunStatus
from core.config import Settings
from guardrails.policy import RiskMode
from sandbox.local import LocalWorkspaceExecutor
from sandbox.workspace import baseline_sha, provision_workspace
from tools.context import ToolContext
from tools.registry import ToolCallRecord, ToolInvoker


def _build_checkpointer() -> InMemorySaver:
    """Checkpointer with a strict deserialization allowlist.

    LangGraph's default is permissive: any type in a checkpoint gets reconstructed.
    Since a checkpoint store is a deserialization surface, we opt into strict mode
    and name exactly the types our state contains.
    """
    from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer

    from agent import schemas
    from agent import state as state_module
    from guardrails.policy import RiskMode

    allowed = [
        state_module.Phase, state_module.RunStatus, state_module.Issue,
        state_module.RunLimits, state_module.Usage, state_module.TestSummary,
        state_module.ApprovalRequest, state_module.AgentError, state_module.StepRecord,
        state_module.AgentState, RiskMode,
        schemas.RiskLevelOut, schemas.Verdict, schemas.IssueSummary,
        schemas.InvestigationPlan, schemas.EvidenceItem, schemas.Hypothesis,
        schemas.ProposedChange, schemas.SolutionProposal, schemas.ReviewerResult,
        schemas.FailureAnalysis, schemas.FinalResult,
    ]
    serde = JsonPlusSerializer(allowed_msgpack_modules=None).with_msgpack_allowlist(allowed)
    return InMemorySaver(serde=serde)


# One checkpointer per process. Interrupt/resume needs the same store across the
# pause, and an in-memory saver is enough while runs live in one process.
_CHECKPOINTER = _build_checkpointer()


@dataclass
class RunHandle:
    run_id: str
    state: AgentState
    interrupted: bool
    interrupt_payload: dict[str, Any] | None = None


def _thread_config(run_id: str, ctx: RunContext) -> RunnableConfig:
    return RunnableConfig(
        configurable={"thread_id": run_id, "run_context": ctx}, recursion_limit=80
    )


class Runner:
    def __init__(
        self, settings: Settings, provider_factory: Callable[[], ModelProvider]
    ) -> None:
        # A factory, not an instance: the scripted provider is stateful, so each
        # run needs its own. `resume` reuses the run's provider via its RunContext,
        # which is what lets a scripted run continue after an approval.
        self._settings = settings
        self._provider_factory = provider_factory
        self._graph = build_graph(_CHECKPOINTER)
        self._contexts: dict[str, RunContext] = {}

    def start(
        self,
        *,
        source_repo: Path,
        issue: Issue,
        risk_mode: RiskMode = RiskMode.STANDARD,
        run_id: str | None = None,
        emit: Callable[[dict[str, Any]], None] | None = None,
    ) -> RunHandle:
        run_id = run_id or uuid.uuid4().hex[:12]
        workspace = provision_workspace(
            source_repo, self._settings.workspace_root, run_id
        )

        executor = LocalWorkspaceExecutor(
            workspace,
            default_timeout_s=self._settings.command_timeout_seconds,
            max_output_bytes=self._settings.max_output_bytes,
        )
        invoker = ToolInvoker(
            ctx=ToolContext(executor=executor, timeout_s=self._settings.command_timeout_seconds),
            risk_mode=risk_mode,
        )
        ctx = RunContext(
            run_id=run_id,
            provider=self._provider_factory(),
            invoker=invoker,
            investigator_model=self._settings.investigator_model,
            reviewer_model=self._settings.reviewer_model,
            demo_mode=self._settings.provider == "fake",
            emit=emit or (lambda _: None),
        )
        self._contexts[run_id] = ctx

        state = AgentState(
            run_id=run_id,
            workspace_path=str(workspace),
            repo_git_sha=baseline_sha(workspace),
            risk_mode=risk_mode,
            issue=issue,
            limits=RunLimits(
                max_steps=self._settings.max_steps,
                max_tool_calls=self._settings.max_tool_calls,
                max_revisions=self._settings.max_revisions,
                max_tokens=self._settings.max_tokens,
                max_wallclock_seconds=self._settings.max_wallclock_seconds,
            ),
        )
        return self._drive(run_id, state.model_dump(), ctx)

    def tool_history(self, run_id: str) -> list[ToolCallRecord]:
        ctx = self._contexts.get(run_id)
        return list(ctx.invoker.history) if ctx else []

    def resume(self, run_id: str, *, approved: bool, comment: str = "") -> RunHandle:
        ctx = self._contexts.get(run_id)
        if ctx is None:
            raise KeyError(f"no active run context for {run_id}")
        from langgraph.types import Command

        return self._drive(
            run_id, Command(resume={"approved": approved, "comment": comment}), ctx
        )

    def _drive(self, run_id: str, payload: Any, ctx: RunContext) -> RunHandle:
        config = _thread_config(run_id, ctx)
        result = self._graph.invoke(payload, config=config)

        snapshot = self._graph.get_state(config)
        interrupts = getattr(snapshot, "interrupts", ()) or ()
        if interrupts:
            state = AgentState.model_validate(snapshot.values)
            state.status = RunStatus.AWAITING_APPROVAL
            return RunHandle(
                run_id=run_id,
                state=state,
                interrupted=True,
                interrupt_payload=dict(interrupts[0].value),
            )

        return RunHandle(run_id=run_id, state=AgentState.model_validate(result), interrupted=False)
