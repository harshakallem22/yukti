from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from sandbox.local import LocalWorkspaceExecutor
from tools.context import ToolContext

BENCHMARK_REPO = Path(__file__).resolve().parent.parent / "benchmarks" / "fastapi_bug_001" / "repo"


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    """A small git repository standing in for a real project."""
    root = tmp_path / "repo"
    (root / "src").mkdir(parents=True)
    (root / "tests").mkdir()
    (root / "src" / "service.py").write_text(
        "def register_user(email):\n"
        "    if email in USERS:\n"
        "        raise DuplicateError(email)\n"
        "    USERS.add(email)\n"
    )
    (root / "src" / "helpers.py").write_text("def slugify(value):\n    return value.lower()\n")
    (root / "tests" / "test_service.py").write_text("def test_ok():\n    assert True\n")
    (root / "README.md").write_text("# Demo project\n")

    subprocess.run(["git", "init", "--quiet"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=root, check=True)
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)
    subprocess.run(["git", "commit", "--quiet", "-m", "init"], cwd=root, check=True)
    return root


@pytest.fixture
def executor(workspace: Path) -> LocalWorkspaceExecutor:
    return LocalWorkspaceExecutor(workspace, default_timeout_s=30, max_output_bytes=8192)


@pytest.fixture
def ctx(executor: LocalWorkspaceExecutor) -> ToolContext:
    return ToolContext(executor=executor, timeout_s=30)
