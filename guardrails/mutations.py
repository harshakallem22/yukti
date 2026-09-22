"""Mutation policy: which writes are safe, which need a human, which never happen.

Classification is by target path and blast radius. Dependency manifests and CI
configs are gated because editing one turns a later install or pipeline run into
execution of code the agent chose.
"""

from __future__ import annotations

import fnmatch
from pathlib import PurePosixPath

from guardrails.policy import BLAST_RADIUS, ActionClass, Decision, RiskLevel, RiskMode

DEPENDENCY_MANIFESTS = (
    "requirements*.txt", "pyproject.toml", "setup.py", "setup.cfg", "Pipfile",
    "poetry.lock", "package.json", "package-lock.json", "yarn.lock",
    "pnpm-lock.yaml", "go.mod", "go.sum", "Cargo.toml", "Gemfile",
)

INFRA_PATTERNS = (
    ".github/workflows/*", ".gitlab-ci.yml", "Dockerfile*", "docker-compose*.yml",
    "Makefile", "*.tf", ".circleci/*",
)

SENSITIVE_KEYWORDS = ("auth", "security", "crypto", "permission", "password", "secret", "token")
MIGRATION_DIRS = ("alembic", "migrations", "db/migrate")


def _matches_any(name: str, patterns: tuple[str, ...]) -> bool:
    return any(fnmatch.fnmatch(name, p) for p in patterns)


def classify_file_write(path: str, *, deleting: bool = False) -> Decision:
    """Classify a single-file mutation by its target path."""
    posix = PurePosixPath(path)
    name = posix.name
    parts = posix.parts

    if deleting:
        return Decision(ActionClass.REQUIRES_APPROVAL, f"deleting '{path}'", RiskLevel.HIGH)

    if _matches_any(name, DEPENDENCY_MANIFESTS):
        return Decision(
            ActionClass.REQUIRES_APPROVAL,
            f"'{name}' is a dependency manifest; changes run third-party code",
            RiskLevel.HIGH,
        )

    if _matches_any(path, INFRA_PATTERNS) or _matches_any(name, INFRA_PATTERNS):
        return Decision(
            ActionClass.REQUIRES_APPROVAL,
            f"'{path}' is build or CI infrastructure",
            RiskLevel.HIGH,
        )

    if any(part in MIGRATION_DIRS for part in parts):
        return Decision(
            ActionClass.REQUIRES_APPROVAL, f"'{path}' is a database migration", RiskLevel.HIGH
        )

    lowered = path.lower()
    if any(keyword in lowered for keyword in SENSITIVE_KEYWORDS):
        return Decision(
            ActionClass.REQUIRES_APPROVAL,
            f"'{path}' looks security-sensitive",
            RiskLevel.MEDIUM,
        )

    return Decision(ActionClass.SAFE, f"ordinary source file '{path}'")


def classify_patch(
    files_changed: list[str],
    lines_changed: int,
    *,
    risk_mode: RiskMode = RiskMode.STANDARD,
    deletions: list[str] | None = None,
) -> Decision:
    """Classify a whole patch: the strictest per-file verdict, then blast radius."""
    for path in deletions or []:
        return classify_file_write(path, deleting=True)

    for path in files_changed:
        decision = classify_file_write(path)
        if decision.action_class is not ActionClass.SAFE:
            return decision

    max_files, max_lines = BLAST_RADIUS[risk_mode]
    if len(files_changed) > max_files:
        return Decision(
            ActionClass.REQUIRES_APPROVAL,
            f"{len(files_changed)} files exceeds the {risk_mode} limit of {max_files}",
            RiskLevel.MEDIUM,
        )
    if lines_changed > max_lines:
        return Decision(
            ActionClass.REQUIRES_APPROVAL,
            f"{lines_changed} changed lines exceeds the {risk_mode} limit of {max_lines}",
            RiskLevel.MEDIUM,
        )

    return Decision(ActionClass.SAFE, f"{len(files_changed)} ordinary source files")
