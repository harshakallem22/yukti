"""Workspace provisioning.

Runs never touch the registered repository. Each run gets a disposable clone, and
the clone is always a git repository — `git diff` is how the agent's changes are
extracted, so a non-git source is initialised into one.
"""

from __future__ import annotations

import shutil
import subprocess
import uuid
from pathlib import Path

from core.errors import ToolError

_COPY_IGNORE = shutil.ignore_patterns(
    ".git", "node_modules", "__pycache__", ".venv", "venv", ".pytest_cache",
    ".mypy_cache", ".ruff_cache", "dist", "build", "*.pyc",
)


def _git(argv: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(  # noqa: S603
        ["git", *argv], cwd=cwd, capture_output=True, text=True, timeout=120, check=False
    )
    if result.returncode != 0:
        raise ToolError(f"git {' '.join(argv)} failed", stderr=result.stderr.strip()[:500])
    return result


def is_git_repo(path: Path) -> bool:
    return (path / ".git").exists()


def provision_workspace(source: Path, workspace_root: Path, run_id: str | None = None) -> Path:
    """Clone `source` into a fresh directory under `workspace_root`."""
    source = source.resolve()
    if not source.is_dir():
        raise ToolError(f"source repository not found: {source}")

    workspace_root.mkdir(parents=True, exist_ok=True)
    destination = workspace_root / (run_id or uuid.uuid4().hex[:12])
    if destination.exists():
        shutil.rmtree(destination)

    if is_git_repo(source):
        # --no-hardlinks: a hardlinked object store would let workspace writes
        # reach the origin repository's objects.
        _git(["clone", "--no-hardlinks", "--quiet", str(source), str(destination)], workspace_root)
    else:
        shutil.copytree(source, destination, ignore=_COPY_IGNORE)
        _init_repo(destination)

    return destination


def _init_repo(path: Path) -> None:
    _git(["init", "--quiet"], path)
    # Identity is set locally so committing works on machines with no global
    # git config, and so the agent's commits are never attributed to the user.
    _git(["config", "user.email", "yukti@localhost"], path)
    _git(["config", "user.name", "Yukti Agent"], path)
    _git(["add", "-A"], path)
    _git(["commit", "--quiet", "-m", "baseline"], path)


def baseline_sha(workspace: Path) -> str:
    return _git(["rev-parse", "HEAD"], workspace).stdout.strip()


def destroy_workspace(workspace: Path) -> None:
    shutil.rmtree(workspace, ignore_errors=True)
