"""Per-run resources that are not part of durable state.

The provider client, tool invoker and event emitter are live objects; the
tool-calling message buffer is large and transient. Keeping them out of
`AgentState` is what stops state from becoming a transcript.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from langchain_core.runnables import RunnableConfig

from agent.providers.base import ModelProvider
from agent.state import Usage
from tools.registry import ToolInvoker

EventEmitter = Callable[[dict[str, Any]], None]


def _noop(_: dict[str, Any]) -> None:
    return None


@dataclass
class RunContext:
    run_id: str
    provider: ModelProvider
    invoker: ToolInvoker
    investigator_model: str = "gpt-4.1"
    reviewer_model: str = "gpt-4.1"
    demo_mode: bool = False
    emit: EventEmitter = _noop
    started_at: float = field(default_factory=time.monotonic)

    # Transient tool-calling buffer for the investigation loop. Not persisted;
    # investigation never interrupts, so it does not need to survive a restart.
    messages: list[dict[str, Any]] = field(default_factory=list)

    _input_tokens: int = 0
    _output_tokens: int = 0
    _cost: float = 0.0
    _model_calls: int = 0

    def record_usage(self, input_tokens: int, output_tokens: int, cost: float) -> None:
        self._input_tokens += input_tokens
        self._output_tokens += output_tokens
        self._cost += cost
        self._model_calls += 1

    def usage(self, steps: int) -> Usage:
        return Usage(
            input_tokens=self._input_tokens,
            output_tokens=self._output_tokens,
            cost_usd=round(self._cost, 6),
            model_calls=self._model_calls,
            tool_calls=self.invoker.call_count,
            duplicate_tool_calls=self.invoker.duplicate_count,
            steps=steps,
        )

    @property
    def elapsed_ms(self) -> int:
        return int((time.monotonic() - self.started_at) * 1000)


def context_from_config(config: RunnableConfig) -> RunContext:
    ctx = (config or {}).get("configurable", {}).get("run_context")
    if not isinstance(ctx, RunContext):
        raise RuntimeError("graph invoked without a RunContext in config.configurable")
    return ctx
