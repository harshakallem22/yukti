"""Repository inspection tools.

Code search is implemented in Python rather than shelling out to ripgrep. That
removes an external binary from the deployment contract, keeps behaviour identical
across machines, and means search obeys the same ignore rules as the tree walk.
The cost is speed on very large repositories, which is not the regime these
benchmark repos are in.
"""

from __future__ import annotations

import fnmatch
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from core.errors import ToolError
from guardrails.filesystem import resolve_in_workspace
from tools.context import IGNORED_DIRS, ToolContext

_BINARY_SNIFF_BYTES = 8192


def _walk(root: Path, *, max_depth: int | None = None) -> Iterator[tuple[Path, int, bool]]:
    stack: list[tuple[Path, int]] = [(root, 0)]
    while stack:
        current, depth = stack.pop()
        try:
            entries = sorted(current.iterdir(), key=lambda p: (p.is_file(), p.name))
        except (PermissionError, OSError):
            continue
        for entry in entries:
            if entry.is_dir():
                if entry.name in IGNORED_DIRS or entry.is_symlink():
                    continue
                if max_depth is None or depth < max_depth:
                    stack.append((entry, depth + 1))
                yield entry, depth, True
            elif entry.is_file() and not entry.is_symlink():
                yield entry, depth, False


def _is_binary(path: Path) -> bool:
    try:
        with path.open("rb") as handle:
            return b"\x00" in handle.read(_BINARY_SNIFF_BYTES)
    except OSError:
        return True


def get_repository_tree(ctx: ToolContext, max_depth: int = 4) -> dict[str, Any]:
    root = ctx.workspace
    entries: list[str] = []
    file_count = 0
    truncated = False

    for path, depth, is_dir in _walk(root, max_depth=max_depth):
        if len(entries) >= ctx.max_tree_entries:
            truncated = True
            break
        relative = path.relative_to(root)
        indent = "  " * depth
        if is_dir:
            entries.append(f"{indent}{relative.name}/")
        else:
            file_count += 1
            entries.append(f"{indent}{relative.name}  ({path.stat().st_size}b)")

    return {
        "tree": "\n".join(entries),
        "file_count": file_count,
        "truncated": truncated,
        "max_depth": max_depth,
    }


def list_directory(ctx: ToolContext, path: str = ".") -> dict[str, Any]:
    resolved = resolve_in_workspace(ctx.workspace, path)
    if not resolved.is_dir():
        raise ToolError(f"not a directory: {path}", path=path)

    directories, files = [], []
    for entry in sorted(resolved.iterdir(), key=lambda p: p.name):
        if entry.name in IGNORED_DIRS:
            continue
        if entry.is_dir():
            directories.append(entry.name)
        elif entry.is_file():
            files.append({"name": entry.name, "size": entry.stat().st_size})

    return {"path": path, "directories": directories, "files": files}


def read_file(
    ctx: ToolContext, path: str, start_line: int | None = None, end_line: int | None = None
) -> dict[str, Any]:
    """Read a file, or a line window of it. Output is line-numbered so the agent
    can cite exact ranges as evidence."""
    resolved = resolve_in_workspace(ctx.workspace, path)
    if not resolved.is_file():
        raise ToolError(f"not a file: {path}", path=path)
    if resolved.stat().st_size > ctx.max_file_bytes:
        raise ToolError(f"file exceeds {ctx.max_file_bytes} bytes", path=path)
    if _is_binary(resolved):
        raise ToolError("cannot read a binary file", path=path)

    lines = resolved.read_text(encoding="utf-8", errors="replace").splitlines()
    total = len(lines)
    lo = max((start_line or 1) - 1, 0)
    hi = min(end_line or total, total)
    window = lines[lo:hi]
    numbered = "\n".join(f"{lo + i + 1:>5} | {line}" for i, line in enumerate(window))

    return {
        "path": path,
        "content": numbered,
        "start_line": lo + 1,
        "end_line": hi,
        "total_lines": total,
        "windowed": (lo, hi) != (0, total),
    }


def search_code(
    ctx: ToolContext,
    query: str,
    *,
    file_pattern: str | None = None,
    regex: bool = False,
    case_sensitive: bool = False,
) -> dict[str, Any]:
    """Search file contents. Returns locations and matching lines, never file bodies."""
    if not query:
        raise ToolError("query must not be empty")

    flags = 0 if case_sensitive else re.IGNORECASE
    try:
        pattern = re.compile(query if regex else re.escape(query), flags)
    except re.error as exc:
        raise ToolError(f"invalid regex: {exc}", query=query) from exc

    root = ctx.workspace
    matches: list[dict[str, Any]] = []
    files_searched = 0
    truncated = False

    for path, _, is_dir in _walk(root):
        if is_dir:
            continue
        relative = str(path.relative_to(root))
        if file_pattern and not fnmatch.fnmatch(relative, file_pattern):
            continue
        if path.stat().st_size > ctx.max_file_bytes or _is_binary(path):
            continue

        files_searched += 1
        try:
            content = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue

        for line_no, line in enumerate(content.splitlines(), start=1):
            if pattern.search(line):
                if len(matches) >= ctx.max_search_results:
                    truncated = True
                    break
                matches.append(
                    {"path": relative, "line": line_no, "text": line.strip()[:240]}
                )
        if truncated:
            break

    return {
        "query": query,
        "matches": matches,
        "match_count": len(matches),
        "files_searched": files_searched,
        "truncated": truncated,
    }


def find_files(ctx: ToolContext, pattern: str) -> dict[str, Any]:
    """Find files whose path or name matches a glob (e.g. `*service*.py`)."""
    root = ctx.workspace
    found: list[str] = []
    truncated = False

    for path, _, is_dir in _walk(root):
        if is_dir:
            continue
        relative = str(path.relative_to(root))
        if fnmatch.fnmatch(relative, pattern) or fnmatch.fnmatch(path.name, pattern):
            if len(found) >= ctx.max_search_results:
                truncated = True
                break
            found.append(relative)

    return {"pattern": pattern, "files": sorted(found), "count": len(found), "truncated": truncated}


def get_file_metadata(ctx: ToolContext, path: str) -> dict[str, Any]:
    resolved = resolve_in_workspace(ctx.workspace, path)
    if not resolved.exists():
        raise ToolError(f"path does not exist: {path}", path=path)
    stat = resolved.stat()
    line_count = None
    if resolved.is_file() and not _is_binary(resolved) and stat.st_size <= ctx.max_file_bytes:
        line_count = len(resolved.read_text(encoding="utf-8", errors="replace").splitlines())
    return {
        "path": path,
        "is_file": resolved.is_file(),
        "size_bytes": stat.st_size,
        "line_count": line_count,
    }
