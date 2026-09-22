"""Yukti MCP server.

Exposes a deliberately narrow slice of Yukti's capabilities over the Model Context
Protocol: read-oriented repository inspection plus test execution. Not every
internal function is published — an MCP tool surface is an API, and publishing
`write_file` over a process boundary would hand arbitrary write access to any
client that connects.

The server enforces guardrails **itself** rather than trusting its caller. It is a
process boundary that other clients (Claude Code, Cursor, an IDE) can attach to,
so it cannot assume the caller is our own agent.

Run standalone:
    python -m yukti_mcp.server /path/to/repository
"""

from __future__ import annotations

import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from mcp.server.mcpserver import MCPServer

from core.errors import YuktiError
from sandbox.local import LocalWorkspaceExecutor
from tools import git, repository, testing
from tools.context import ToolContext

_ctx: ToolContext | None = None


def configure(workspace: Path, *, timeout_s: int = 120) -> ToolContext:
    global _ctx
    _ctx = ToolContext(executor=LocalWorkspaceExecutor(workspace), timeout_s=timeout_s)
    return _ctx


def _context() -> ToolContext:
    if _ctx is None:
        raise RuntimeError("MCP server is not configured with a workspace")
    return _ctx


def _guarded(fn: Callable[..., dict[str, Any]], **kwargs: Any) -> dict[str, Any]:
    """Convert guardrail refusals into structured tool results.

    A rejected call is a normal, reportable outcome — the client learns why
    instead of receiving an opaque transport error.
    """
    try:
        return dict(fn(_context(), **kwargs))
    except YuktiError as exc:
        return exc.to_observation()


server: MCPServer = MCPServer(
    name="yukti",
    version="0.1.0",
    instructions=(
        "Read-only repository inspection and test execution for a single "
        "configured workspace. All paths are workspace-relative; traversal "
        "outside the workspace is refused."
    ),
)


@server.tool(name="repo.get_tree", description="Show the repository file tree.")
def repo_get_tree(max_depth: int = 4) -> dict[str, Any]:
    return _guarded(repository.get_repository_tree, max_depth=max_depth)


@server.tool(
    name="repo.search_code",
    description="Search file contents. Returns matching paths and line numbers, not file bodies.",
)
def repo_search_code(
    query: str, file_pattern: str | None = None, regex: bool = False
) -> dict[str, Any]:
    return _guarded(
        repository.search_code, query=query, file_pattern=file_pattern, regex=regex
    )


@server.tool(
    name="repo.read_file",
    description="Read a workspace file with line numbers. Prefer a line window over a whole file.",
)
def repo_read_file(
    path: str, start_line: int | None = None, end_line: int | None = None
) -> dict[str, Any]:
    return _guarded(repository.read_file, path=path, start_line=start_line, end_line=end_line)


@server.tool(name="repo.find_files", description="Find files by glob pattern, e.g. '*service*.py'.")
def repo_find_files(pattern: str) -> dict[str, Any]:
    return _guarded(repository.find_files, pattern=pattern)


@server.tool(name="git.diff", description="Show uncommitted changes in the workspace.")
def git_diff(path: str | None = None) -> dict[str, Any]:
    return _guarded(git.git_diff, path=path)


@server.tool(
    name="testing.run_tests",
    description="Run the workspace test suite, optionally narrowed to a file or -k expression.",
)
def testing_run_tests(target: str | None = None) -> dict[str, Any]:
    return _guarded(testing.run_tests, target=target)


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if not args:
        print("usage: python -m yukti_mcp.server <repository-path>", file=sys.stderr)
        return 2

    workspace = Path(args[0]).expanduser().resolve()
    if not workspace.is_dir():
        print(f"not a directory: {workspace}", file=sys.stderr)
        return 2

    configure(workspace)
    server.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
