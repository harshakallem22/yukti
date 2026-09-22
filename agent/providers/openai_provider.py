"""OpenAI provider.

Structured output uses the SDK's schema-constrained `parse`, which makes malformed
output rare — but it is still validated and still has a bounded repair path.
A provider guarantee is not a reason to skip validation.
"""

from __future__ import annotations

import json
import time
from typing import Any, TypeVar

from openai import APIError, APITimeoutError, OpenAI, RateLimitError
from pydantic import BaseModel

from agent.providers.base import ModelResponse, StructuredResponse, ToolCall, estimate_cost
from core.errors import ModelError, SchemaValidationError

T = TypeVar("T", bound=BaseModel)

_MAX_REPAIRS = 2


class OpenAIProvider:
    def __init__(
        self,
        api_key: str,
        *,
        default_model: str = "gpt-4.1",
        timeout: int = 120,
        max_retries: int = 3,
    ) -> None:
        self._client = OpenAI(api_key=api_key, timeout=timeout, max_retries=max_retries)
        self._default_model = default_model

    def _call(self, **kwargs: Any) -> Any:
        try:
            return self._client.chat.completions.create(**kwargs)
        except (APITimeoutError, RateLimitError) as exc:
            raise ModelError(f"model unavailable: {exc}") from exc
        except APIError as exc:
            raise ModelError(f"model request failed: {exc}") from exc

    def generate(
        self,
        *,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
    ) -> ModelResponse:
        chosen = model or self._default_model
        payload: dict[str, Any] = {
            "model": chosen,
            "messages": [{"role": "system", "content": system}, *messages],
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        response = self._call(**payload)
        choice = response.choices[0]
        usage = response.usage

        calls = []
        for call in choice.message.tool_calls or []:
            try:
                arguments = json.loads(call.function.arguments or "{}")
            except json.JSONDecodeError:
                # Malformed arguments are surfaced to the agent as a tool error
                # rather than crashing the run.
                arguments = {"__malformed__": call.function.arguments}
            calls.append(ToolCall(id=call.id, name=call.function.name, arguments=arguments))

        return ModelResponse(
            text=choice.message.content or "",
            tool_calls=calls,
            input_tokens=usage.prompt_tokens if usage else 0,
            output_tokens=usage.completion_tokens if usage else 0,
            cost_usd=estimate_cost(
                chosen,
                usage.prompt_tokens if usage else 0,
                usage.completion_tokens if usage else 0,
            ),
            model=chosen,
            finish_reason=choice.finish_reason or "",
        )

    def generate_structured(
        self, *, system: str, user: str, schema: type[T], model: str | None = None
    ) -> StructuredResponse[T]:
        chosen = model or self._default_model
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]
        input_tokens = output_tokens = 0

        for attempt in range(_MAX_REPAIRS + 1):
            try:
                response = self._client.chat.completions.parse(
                    model=chosen,
                    messages=messages,  # type: ignore[arg-type]
                    response_format=schema,
                )
            except (APITimeoutError, RateLimitError) as exc:
                raise ModelError(f"model unavailable: {exc}") from exc
            except APIError as exc:
                raise ModelError(f"model request failed: {exc}") from exc

            if response.usage:
                input_tokens += response.usage.prompt_tokens
                output_tokens += response.usage.completion_tokens

            parsed = response.choices[0].message.parsed
            if parsed is not None:
                return StructuredResponse(
                    value=parsed,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    cost_usd=estimate_cost(chosen, input_tokens, output_tokens),
                    model=chosen,
                    repair_attempts=attempt,
                )

            refusal = response.choices[0].message.refusal or "no content returned"
            if attempt == _MAX_REPAIRS:
                break
            # Bounded repair: re-ask once with the failure made explicit.
            messages.append({"role": "assistant", "content": refusal})
            messages.append(
                {
                    "role": "user",
                    "content": "That response did not match the required schema. "
                    "Return only a valid object matching the schema.",
                }
            )
            time.sleep(0.5 * (attempt + 1))

        raise SchemaValidationError(
            f"model did not return valid {schema.__name__} after {_MAX_REPAIRS} repairs"
        )
