"""Git tools.

All git access goes through the git binary rather than reading `.git` directly —
the filesystem jail denies `.git` precisely so that a write to `.git/hooks/*`
cannot turn a later git invocation into arbitrary code execution.
"""

from __future__ import annotations

from typing import Any

from core.errors import ToolError
from tools.context import ToolContext


def _run_git(ctx: ToolContext, argv: list[str]) -> str:
    # Subcommands here are fixed and read-only; agent-supplied commands are
    # classified once, at registry dispatch, rather than in each tool.
    result = ctx.executor.run(["git", *argv], timeout_s=ctx.timeout_s)
    if result.exit_code != 0:
        raise ToolError(f"git {argv[0]} failed", stderr=result.stderr.strip()[:500])
    return result.stdout


def git_status(ctx: ToolContext) -> dict[str, Any]:
    output = _run_git(ctx, ["status", "--porcelain"])
    changes = []
    for line in output.splitlines():
        if len(line) > 3:
            changes.append({"status": line[:2].strip(), "path": line[3:]})
    return {"changes": changes, "clean": not changes}


def git_diff(ctx: ToolContext, path: str | None = None) -> dict[str, Any]:
    argv = ["diff", "HEAD"]
    if path:
        argv += ["--", path]
    diff = _run_git(ctx, argv)
    stat = _run_git(ctx, ["diff", "HEAD", "--numstat"])

    files, added, removed = [], 0, 0
    for line in stat.splitlines():
        parts = line.split("\t")
        if len(parts) == 3:
            # Binary files report "-" instead of a count.
            a = int(parts[0]) if parts[0].isdigit() else 0
            r = int(parts[1]) if parts[1].isdigit() else 0
            added += a
            removed += r
            files.append({"path": parts[2], "added": a, "removed": r})

    return {
        "diff": diff,
        "files_changed": [f["path"] for f in files],
        "file_stats": files,
        "lines_added": added,
        "lines_removed": removed,
        "is_empty": not diff.strip(),
    }


def git_log(ctx: ToolContext, limit: int = 10) -> dict[str, Any]:
    output = _run_git(ctx, ["log", f"-{limit}", "--pretty=format:%H%x1f%an%x1f%ar%x1f%s"])
    commits = []
    for line in output.splitlines():
        parts = line.split("\x1f")
        if len(parts) == 4:
            commits.append(
                {"sha": parts[0][:10], "author": parts[1], "when": parts[2], "subject": parts[3]}
            )
    return {"commits": commits}


def git_show(ctx: ToolContext, commit: str) -> dict[str, Any]:
    if not commit.replace("~", "").replace("^", "").isalnum():
        raise ToolError("invalid commit reference", commit=commit)
    return {"commit": commit, "content": _run_git(ctx, ["show", "--stat", commit])}
