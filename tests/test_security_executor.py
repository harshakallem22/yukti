"""Security tests 12-14: process isolation."""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import pytest

from sandbox.local import LocalWorkspaceExecutor

pytestmark = pytest.mark.security


def test_command_timeout_kills_process(executor: LocalWorkspaceExecutor) -> None:
    (executor.workspace_root / "sleeper.py").write_text("import time; time.sleep(60)\n")
    started = time.monotonic()
    result = executor.run([sys.executable, "sleeper.py"], timeout_s=2)
    elapsed = time.monotonic() - started

    assert result.timed_out
    assert elapsed < 15, "timeout must actually terminate the process, not wait it out"


def test_command_timeout_kills_process_group(executor: LocalWorkspaceExecutor) -> None:
    """A test runner spawns children. Killing only the parent orphans them, so the
    executor kills the whole process group."""
    root = executor.workspace_root
    (root / "grandchild.py").write_text(
        "import subprocess, sys, pathlib\n"
        "p = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
        "pathlib.Path('grandchild.pid').write_text(str(p.pid))\n"
        "import time; time.sleep(60)\n"
    )
    result = executor.run([sys.executable, "grandchild.py"], timeout_s=3)
    assert result.timed_out

    pid_file = root / "grandchild.pid"
    assert pid_file.exists(), "child process should have started before the timeout"
    grandchild_pid = int(pid_file.read_text())

    time.sleep(0.5)
    with pytest.raises(OSError):
        # Signal 0 probes liveness without sending anything.
        os.kill(grandchild_pid, 0)


def test_subprocess_env_excludes_secrets(
    executor: LocalWorkspaceExecutor, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The agent runs test suites from repositories it did not write. Inheriting
    os.environ would hand every one of them the API key."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-secret-value-must-not-leak")
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:password@host/db")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "aws-secret-must-not-leak")

    (executor.workspace_root / "dump_env.py").write_text(
        "import os, json; print(json.dumps(dict(os.environ)))\n"
    )
    result = executor.run([sys.executable, "dump_env.py"])

    assert result.exit_code == 0
    assert "sk-secret-value-must-not-leak" not in result.stdout
    assert "password" not in result.stdout
    assert "aws-secret-must-not-leak" not in result.stdout
    assert "OPENAI_API_KEY" not in result.stdout
    assert "DATABASE_URL" not in result.stdout


def test_output_truncation_flagged(executor: LocalWorkspaceExecutor) -> None:
    """Truncated output must be *marked* truncated: an agent that believes it saw
    a whole file will reason confidently from a false premise."""
    (executor.workspace_root / "flood.py").write_text("print('x' * 500_000)\n")
    result = executor.run([sys.executable, "flood.py"])

    assert result.truncated
    assert len(result.stdout.encode()) <= 8192


def test_working_directory_is_pinned(executor: LocalWorkspaceExecutor) -> None:
    (executor.workspace_root / "cwd.py").write_text("import os; print(os.getcwd())\n")
    result = executor.run([sys.executable, "cwd.py"])
    assert Path(result.stdout.strip()).resolve() == executor.workspace_root.resolve()


def test_missing_binary_raises_tool_error(executor: LocalWorkspaceExecutor) -> None:
    from core.errors import ToolError

    with pytest.raises(ToolError):
        executor.run(["definitely-not-a-real-binary-xyz"])


def test_home_is_not_the_real_home(executor: LocalWorkspaceExecutor) -> None:
    """HOME points at a scratch dir so a subprocess cannot read ~/.ssh or ~/.aws
    by expanding '~'."""
    (executor.workspace_root / "home.py").write_text(
        "import os; print(os.path.expanduser('~'))\n"
    )
    result = executor.run([sys.executable, "home.py"])
    assert result.stdout.strip() != str(Path.home())
