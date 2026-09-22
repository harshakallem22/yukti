"""Shared policy vocabulary.

Every guardrail returns a `Decision`. Nothing returns a bare bool, because "why"
is what the approval UI shows the human and what the compliance evaluator reads.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class ActionClass(StrEnum):
    SAFE = "SAFE"
    REQUIRES_APPROVAL = "REQUIRES_APPROVAL"
    BLOCKED = "BLOCKED"


class RiskLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class RiskMode(StrEnum):
    CONSERVATIVE = "conservative"
    STANDARD = "standard"
    EXPERIMENTAL = "experimental"


@dataclass(frozen=True)
class Decision:
    action_class: ActionClass
    reason: str
    risk: RiskLevel = RiskLevel.LOW

    @property
    def allowed(self) -> bool:
        return self.action_class is ActionClass.SAFE

    @property
    def blocked(self) -> bool:
        return self.action_class is ActionClass.BLOCKED


# Blast-radius ceilings per risk mode. Modes shift thresholds only; no mode can
# promote a BLOCKED action to anything else.
BLAST_RADIUS: dict[RiskMode, tuple[int, int]] = {
    RiskMode.CONSERVATIVE: (3, 100),
    RiskMode.STANDARD: (10, 400),
    RiskMode.EXPERIMENTAL: (25, 1000),
}


def action_hash(action: dict[str, Any]) -> str:
    """Stable fingerprint of an action, used to bind a human approval to it.

    Approval authorises this exact action. Recomputing the hash at execution time
    and comparing prevents an approved decision from being reused for a different
    action after the graph resumes.
    """
    canonical = json.dumps(action, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()


def approval_hash(path: str, reason: str) -> str:
    """Fingerprint for a file-mutation approval.

    Keyed on the file and the triggering rule, not the tool: a human approving
    "you may modify package.json" is authorising the mutation itself, so the
    same grant covers write_file and replace_in_file — but not a different file.
    """
    return action_hash({"action": "modify_file", "path": path, "reason": reason})
