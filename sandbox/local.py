"""Local workspace executor.

Isolation properties: disposable clone, cwd pinned, no shell, constructed
environment, process-group kill on timeout, disk-bounded output capture.

Known limitation: this shares the host kernel and user. The command allowlist
governs what Yukti *launches*, not what a launched process then does. A test file
calling `os.remove()` on a host path is not stopped here. DockerExecutor closes
that gap; until then the honest word is "isolated workspace", not "sandboxed".
"""

from __future__ import annotations

import contextlib
import os
import signal
import subprocess
import tempfile
import time
from pathlib import Path

from core.errors import ToolError
from guardrails.filesystem import resolve_in_workspace
from sandbox.executor import ExecResult

# Inherited wholesale from the parent process, nothing else. `os.environ` is never
# passed through: it holds OPENAI_API_KEY and DATABASE_URL, and the agent runs test
# suites from repositories it did not write.
_INHERITED_VARS = ("PATH", "LANG", "LC_ALL", "SYSTEMROOT")


class LocalWorkspaceExecutor:
    def __init__(
        self,
        workspace_root: Path,
        *,
        default_timeout_s: int = 120,
        max_output_bytes: int = 262_144,
    ) -> None:
        self._root = workspace_root.resolve()
        self._default_timeout_s = default_timeout_s
        self._max_output_bytes = max_output_bytes
        self._home = Path(tempfile.mkdtemp(prefix="yukti-home-"))

    @property
    def workspace_root(self) -> Path:
        return self._root

    def _build_env(self) -> dict[str, str]:
        env = {var: os.environ[var] for var in _INHERITED_VARS if var in os.environ}
        env.update(
            {
                "HOME": str(self._home),
                "TMPDIR": str(self._home),
                "PYTHONHASHSEED": "0",
                "PYTHONDONTWRITEBYTECODE": "1",
                "PYTHONUNBUFFERED": "1",
                "NO_COLOR": "1",
                "CI": "1",
            }
        )
        return env

    def _read_capped(self, handle: tempfile.SpooledTemporaryFile[bytes]) -> tuple[str, bool]:
        handle.seek(0)
        raw = handle.read(self._max_output_bytes + 1)
        truncated = len(raw) > self._max_output_bytes
        return raw[: self._max_output_bytes].decode("utf-8", errors="replace"), truncated

    def run(self, argv: list[str], *, timeout_s: int | None = None) -> ExecResult:
        timeout = timeout_s or self._default_timeout_s
        started = time.monotonic()

        # Output goes to temp files rather than pipes so a runaway process bounds
        # disk rather than this process's memory.
        with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
            try:
                process = subprocess.Popen(  # noqa: S603 - argv list, shell=False by construction
                    argv,
                    cwd=self._root,
                    env=self._build_env(),
                    stdout=out,
                    stderr=err,
                    stdin=subprocess.DEVNULL,
                    shell=False,
                    start_new_session=True,
                )
            except FileNotFoundError as exc:
                raise ToolError(f"command not found: {argv[0]}", argv=argv) from exc

            timed_out = False
            try:
                process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                timed_out = True
                self._kill_process_group(process)

            stdout, out_truncated = self._read_capped(out)  # type: ignore[arg-type]
            stderr, err_truncated = self._read_capped(err)  # type: ignore[arg-type]

        return ExecResult(
            argv=argv,
            exit_code=process.returncode if process.returncode is not None else -1,
            stdout=stdout,
            stderr=stderr,
            duration_ms=int((time.monotonic() - started) * 1000),
            timed_out=timed_out,
            truncated=out_truncated or err_truncated,
        )

    @staticmethod
    def _kill_process_group(process: subprocess.Popen[bytes]) -> None:
        # start_new_session put the child in its own group; killing the group
        # reaps test-runner children instead of orphaning them.
        try:
            os.killpg(os.getpgid(process.pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            process.kill()
        with contextlib.suppress(subprocess.TimeoutExpired):
            process.wait(timeout=5)

    def read_file(self, path: str, start: int | None = None, end: int | None = None) -> str:
        resolved = resolve_in_workspace(self._root, path)
        if not resolved.is_file():
            raise ToolError(f"not a file: {path}", path=path)
        text = resolved.read_text(encoding="utf-8", errors="replace")
        if start is None and end is None:
            return text
        lines = text.splitlines()
        lo = max((start or 1) - 1, 0)
        hi = min(end or len(lines), len(lines))
        return "\n".join(lines[lo:hi])

    def write_file(self, path: str, content: str) -> None:
        resolved = resolve_in_workspace(self._root, path)
        resolved.parent.mkdir(parents=True, exist_ok=True)
        resolved.write_text(content, encoding="utf-8")

    def exists(self, path: str) -> bool:
        try:
            return resolve_in_workspace(self._root, path).exists()
        except Exception:
            return False
