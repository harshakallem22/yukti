"""Tool registry and dispatch.

This is the single enforcement point. Every agent-initiated tool call passes
through `ToolInvoker.invoke`, which validates arguments, applies policy, detects
duplicates, and records the call. Individual tools assume they were authorised —
scattering checks across tools would mean auditing every tool to know what the
agent can do.
"""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from core.errors import ApprovalRequired, PolicyViolation, ToolError, YuktiError
from guardrails.mutations import classify_file_write
from guardrails.policy import ActionClass, RiskMode, approval_hash
from tools import editing, git, repository, testing
from tools.context import ToolContext


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, Any]
    handler: Callable[..., dict[str, Any]]
    mutating: bool = False


def _schema(properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {"type": "object", "properties": properties, "required": required,
            "additionalProperties": False}


_STR = {"type": "string"}
_INT = {"type": "integer"}

TOOLS: dict[str, ToolSpec] = {
    spec.name: spec
    for spec in [
        ToolSpec(
            "get_repository_tree",
            "Show the repository file tree. Start here to orient yourself.",
            _schema({"max_depth": {**_INT, "description": "Depth limit, default 4"}}, []),
            repository.get_repository_tree,
        ),
        ToolSpec(
            "list_directory",
            "List files and subdirectories of one directory.",
            _schema({"path": {**_STR, "description": "Workspace-relative path"}}, ["path"]),
            repository.list_directory,
        ),
        ToolSpec(
            "read_file",
            "Read a file with line numbers. Prefer a line window over a whole file.",
            _schema(
                {
                    "path": _STR,
                    "start_line": {**_INT, "description": "1-indexed, inclusive"},
                    "end_line": {**_INT, "description": "1-indexed, inclusive"},
                },
                ["path"],
            ),
            repository.read_file,
        ),
        ToolSpec(
            "search_code",
            "Search file contents. Returns matching file paths and line numbers.",
            _schema(
                {
                    "query": {**_STR, "description": "Literal text unless regex=true"},
                    "file_pattern": {**_STR, "description": "Glob filter, e.g. '*.py'"},
                    "regex": {"type": "boolean"},
                },
                ["query"],
            ),
            repository.search_code,
        ),
        ToolSpec(
            "find_files",
            "Find files by glob pattern, e.g. '*service*.py'.",
            _schema({"pattern": _STR}, ["pattern"]),
            repository.find_files,
        ),
        ToolSpec(
            "git_diff",
            "Show changes made in this workspace so far.",
            _schema({"path": _STR}, []),
            git.git_diff,
        ),
        ToolSpec(
            "run_tests",
            "Run the test suite. Optionally narrow to a test file or -k expression.",
            _schema({"target": {**_STR, "description": "Test path or keyword expression"}}, []),
            testing.run_tests,
        ),
        ToolSpec(
            "write_file",
            "Overwrite a file with new content. Use replace_in_file for small edits.",
            _schema({"path": _STR, "content": _STR}, ["path", "content"]),
            editing.write_file,
            mutating=True,
        ),
        ToolSpec(
            "replace_in_file",
            "Replace an exact unique snippet in a file. Preferred for targeted edits.",
            _schema({"path": _STR, "old": _STR, "new": _STR}, ["path", "old", "new"]),
            editing.replace_in_file,
            mutating=True,
        ),
    ]
}


def openai_tool_schemas(names: list[str] | None = None) -> list[dict[str, Any]]:
    selected = [TOOLS[n] for n in names] if names else list(TOOLS.values())
    return [
        {
            "type": "function",
            "function": {
                "name": spec.name,
                "description": spec.description,
                "parameters": spec.parameters,
            },
        }
        for spec in selected
    ]


@dataclass
class ToolCallRecord:
    seq: int
    name: str
    arguments: dict[str, Any]
    arguments_hash: str
    status: str
    result: dict[str, Any]
    duration_ms: int
    duplicate_of: int | None = None


def _hash_arguments(name: str, arguments: dict[str, Any]) -> str:
    canonical = json.dumps({"tool": name, "args": arguments}, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()[:16]


@dataclass
class ToolInvoker:
    ctx: ToolContext
    risk_mode: RiskMode = RiskMode.STANDARD
    approved_hashes: set[str] = field(default_factory=set)
    history: list[ToolCallRecord] = field(default_factory=list)
    _seen: dict[str, int] = field(default_factory=dict)

    @property
    def call_count(self) -> int:
        return len(self.history)

    @property
    def duplicate_count(self) -> int:
        return sum(1 for record in self.history if record.duplicate_of is not None)

    def _check_policy(self, spec: ToolSpec, arguments: dict[str, Any]) -> None:
        if not spec.mutating:
            return
        path = str(arguments.get("path", ""))
        decision = classify_file_write(path)
        if decision.action_class is ActionClass.BLOCKED:
            raise PolicyViolation(decision.reason, path=path, risk=decision.risk)
        if decision.action_class is ActionClass.REQUIRES_APPROVAL:
            # Keyed on the file, not the tool: a human approving "you may modify
            # package.json" is authorising the mutation, not one particular editor
            # call. Keying on the tool would force two approvals for one decision.
            digest = approval_hash(path, decision.reason)
            if digest not in self.approved_hashes:
                raise ApprovalRequired(
                    decision.reason,
                    action_hash=digest,
                    tool=spec.name,
                    path=path,
                    risk=str(decision.risk),
                )

    def invoke(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        spec = TOOLS.get(name)
        if spec is None:
            raise ToolError(f"unknown tool: {name}", available=sorted(TOOLS))

        missing = [k for k in spec.parameters["required"] if k not in arguments]
        if missing:
            raise ToolError(f"missing required arguments: {missing}", tool=name)
        unknown = [k for k in arguments if k not in spec.parameters["properties"]]
        if unknown:
            raise ToolError(f"unknown arguments: {unknown}", tool=name)

        self._check_policy(spec, arguments)

        digest = _hash_arguments(name, arguments)
        # Reads are idempotent, so a repeat is waste rather than an error; it is
        # recorded as a trajectory-quality signal and the cached result returned.
        duplicate_of = self._seen.get(digest) if not spec.mutating else None

        started = time.monotonic()
        try:
            result = spec.handler(self.ctx, **arguments)
            status = "ok"
        except YuktiError as exc:
            result = exc.to_observation()
            status = "error"
        duration_ms = int((time.monotonic() - started) * 1000)

        record = ToolCallRecord(
            seq=len(self.history),
            name=name,
            arguments=arguments,
            arguments_hash=digest,
            status=status,
            result=result,
            duration_ms=duration_ms,
            duplicate_of=duplicate_of,
        )
        self.history.append(record)
        self._seen.setdefault(digest, record.seq)

        if duplicate_of is not None:
            result = {**result, "_note": f"identical call already made at step {duplicate_of}"}
        return result

    def files_examined(self) -> list[str]:
        paths = []
        for record in self.history:
            if record.name in {"read_file", "write_file", "replace_in_file"}:
                path = record.arguments.get("path")
                if isinstance(path, str) and path not in paths:
                    paths.append(path)
        return paths
