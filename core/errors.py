"""Structured error hierarchy.

Errors carry enough shape for the agent loop to route on them: `retryable` decides
whether a bounded retry is legitimate, and `to_observation()` renders the error back
to the model as a tool result rather than crashing the run.
"""

from __future__ import annotations

from typing import Any


class YuktiError(Exception):
    retryable: bool = False
    error_type: str = "yukti_error"

    def __init__(self, message: str, **details: Any) -> None:
        super().__init__(message)
        self.message = message
        self.details = details

    def to_observation(self) -> dict[str, Any]:
        return {
            "status": "error",
            "error_type": self.error_type,
            "message": self.message,
            "retryable": self.retryable,
            **self.details,
        }


class PolicyViolation(YuktiError):
    """A guardrail refused the action. Never retryable — retrying is the attack."""

    error_type = "policy_violation"
    retryable = False


class PathTraversalError(PolicyViolation):
    error_type = "path_traversal"


class ApprovalRequired(YuktiError):
    """Control-flow signal, not a failure: the run pauses for a human decision."""

    error_type = "approval_required"

    def __init__(self, message: str, *, action_hash: str, **details: Any) -> None:
        super().__init__(message, action_hash=action_hash, **details)
        self.action_hash = action_hash


class ToolError(YuktiError):
    error_type = "tool_error"
    retryable = True


class SandboxTimeout(ToolError):
    error_type = "sandbox_timeout"
    retryable = False


class BudgetExceeded(YuktiError):
    """A hard run limit was hit. Terminal by design — the run escalates."""

    error_type = "budget_exceeded"
    retryable = False


class SchemaValidationError(YuktiError):
    """Model output failed schema validation; bounded repair may be attempted."""

    error_type = "schema_invalid"
    retryable = True


class ModelError(YuktiError):
    error_type = "model_error"
    retryable = True
