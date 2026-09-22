"""Scripted provider — a test double, not a model.

Purpose: make the graph, the tool loop, the approval flow, the API and the UI
testable and demoable with no API key, no network and no spend.

**This is not Yukti solving anything.** It replays a fixed sequence of decisions.
Any run using it is marked `demo_mode=True` on the run record, badged in the UI,
and refused by the evaluation harness — a benchmark scored against canned output
would be a fabricated metric.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any, TypeVar

from pydantic import BaseModel

from agent.providers.base import ModelResponse, StructuredResponse, ToolCall
from core.errors import ModelError

T = TypeVar("T", bound=BaseModel)


class ScriptedProvider:
    """Replays queued responses in order.

    `structured` is keyed by schema name so nodes can be exercised in any order;
    `generate` responses are consumed as a queue.
    """

    def __init__(
        self,
        *,
        generations: list[ModelResponse] | None = None,
        structured: dict[str, list[BaseModel]] | None = None,
    ) -> None:
        self._generations: Iterator[ModelResponse] = iter(generations or [])
        self._structured = {k: iter(v) for k, v in (structured or {}).items()}
        self.calls: list[str] = []

    def generate(
        self,
        *,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
    ) -> ModelResponse:
        self.calls.append("generate")
        try:
            return next(self._generations)
        except StopIteration:
            # Exhausting the script means the graph took an unscripted path —
            # a real signal in a test, not something to paper over.
            raise ModelError("scripted provider exhausted: unexpected generate() call") from None

    def generate_structured(
        self, *, system: str, user: str, schema: type[T], model: str | None = None
    ) -> StructuredResponse[T]:
        name = schema.__name__
        self.calls.append(f"structured:{name}")
        queue = self._structured.get(name)
        if queue is None:
            raise ModelError(f"scripted provider has no response for {name}")
        try:
            value = next(queue)
        except StopIteration:
            raise ModelError(f"scripted provider exhausted for {name}") from None
        return StructuredResponse(
            value=value,  # type: ignore[arg-type]
            input_tokens=500,
            output_tokens=150,
            cost_usd=0.0,
            model="scripted",
        )


def tool_response(name: str, arguments: dict[str, Any], call_id: str = "call_1") -> ModelResponse:
    return ModelResponse(
        tool_calls=[ToolCall(id=call_id, name=name, arguments=arguments)],
        input_tokens=400,
        output_tokens=60,
        model="scripted",
        finish_reason="tool_calls",
    )


def text_response(text: str) -> ModelResponse:
    return ModelResponse(
        text=text, input_tokens=400, output_tokens=60, model="scripted", finish_reason="stop"
    )
