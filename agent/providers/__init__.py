from agent.providers.base import (
    ModelProvider,
    ModelResponse,
    StructuredResponse,
    ToolCall,
    estimate_cost,
)
from agent.providers.openai_provider import OpenAIProvider
from agent.providers.scripted import ScriptedProvider, text_response, tool_response
from core.config import Settings

__all__ = [
    "ModelProvider",
    "ModelResponse",
    "OpenAIProvider",
    "ScriptedProvider",
    "StructuredResponse",
    "ToolCall",
    "estimate_cost",
    "text_response",
    "tool_response",
]


def build_provider(settings: "Settings") -> ModelProvider:
    """Select a provider from configuration. Kept trivial deliberately — this is a
    seam, not a plugin system."""
    if settings.provider == "fake":
        from agent.providers.demo import demo_provider

        return demo_provider()
    if not settings.openai_api_key:
        raise ValueError(
            "OPENAI_API_KEY is not set. Set it in .env, or set YUKTI_MODEL_PROVIDER=fake "
            "to run in scripted demo mode."
        )
    return OpenAIProvider(
        settings.openai_api_key,
        default_model=settings.investigator_model,
        timeout=settings.model_timeout_seconds,
        max_retries=settings.model_max_retries,
    )
