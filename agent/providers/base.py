"""Model provider seam.

Two methods, on purpose. This exists to swap providers and to inject a fake in
tests — not to abstract over every vendor feature. See ADR 007.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Generic, Protocol, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)

# USD per 1M tokens. Versioned here so historical run costs stay explainable when
# list prices change.
PRICING: dict[str, tuple[float, float]] = {
    "gpt-4.1": (2.00, 8.00),
    "gpt-4.1-mini": (0.40, 1.60),
    "gpt-4o": (2.50, 10.00),
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-5": (1.25, 10.00),
    "gpt-5-mini": (0.25, 2.00),
}
_FALLBACK_PRICE = (2.00, 8.00)


def estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    price_in, price_out = PRICING.get(model, _FALLBACK_PRICE)
    return round((input_tokens * price_in + output_tokens * price_out) / 1_000_000, 6)


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class ModelResponse:
    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    model: str = ""
    finish_reason: str = ""


@dataclass
class StructuredResponse(Generic[T]):
    value: T
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    model: str = ""
    repair_attempts: int = 0


class ModelProvider(Protocol):
    def generate(
        self,
        *,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
    ) -> ModelResponse: ...

    def generate_structured(
        self,
        *,
        system: str,
        user: str,
        schema: type[T],
        model: str | None = None,
    ) -> StructuredResponse[T]: ...
