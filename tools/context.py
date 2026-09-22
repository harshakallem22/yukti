from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from sandbox.executor import SandboxExecutor

IGNORED_DIRS = frozenset(
    {
        ".git", "node_modules", "__pycache__", ".venv", "venv", ".pytest_cache",
        ".mypy_cache", ".ruff_cache", "dist", "build", ".next", "coverage",
        ".idea", ".vscode", "htmlcov", ".tox", "target",
    }
)


@dataclass
class ToolContext:
    executor: SandboxExecutor
    max_search_results: int = 80
    max_tree_entries: int = 400
    max_file_bytes: int = 2_000_000
    timeout_s: int = 120
    extra: dict[str, object] = field(default_factory=dict)

    @property
    def workspace(self) -> Path:
        return self.executor.workspace_root
