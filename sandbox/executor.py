"""Executor protocol.

Policy enforcement lives *above* this interface, so every implementation inherits
the same path jail, command allowlist and budgets. Docker adds a kernel boundary;
it is not the only boundary. See ADR 004.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True)
class ExecResult:
    argv: list[str]
    exit_code: int
    stdout: str
    stderr: str
    duration_ms: int
    timed_out: bool = False
    truncated: bool = False

    @property
    def ok(self) -> bool:
        return self.exit_code == 0 and not self.timed_out


class SandboxExecutor(Protocol):
    @property
    def workspace_root(self) -> Path: ...

    def run(self, argv: list[str], *, timeout_s: int | None = None) -> ExecResult: ...

    def read_file(self, path: str, start: int | None = None, end: int | None = None) -> str: ...

    def write_file(self, path: str, content: str) -> None: ...

    def exists(self, path: str) -> bool: ...
