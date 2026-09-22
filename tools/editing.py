"""Editing tools.

The agent edits through `write_file` and `replace_in_file`; the *patch* is then
derived from `git diff` in the workspace. Asking a model to emit a valid unified
diff with correct line offsets is a well-known reliability problem — the hunk
headers are wrong often enough to matter. Deriving the diff from the resulting
filesystem state gives the same artifact without that failure mode.

`apply_patch` still exists for callers that already hold a valid diff.
"""

from __future__ import annotations

from typing import Any

from core.errors import ToolError
from guardrails.filesystem import resolve_in_workspace
from tools.context import ToolContext


def write_file(ctx: ToolContext, path: str, content: str) -> dict[str, Any]:
    resolved = resolve_in_workspace(ctx.workspace, path)
    existed = resolved.is_file()
    previous_lines = (
        len(resolved.read_text(encoding="utf-8", errors="replace").splitlines()) if existed else 0
    )
    ctx.executor.write_file(path, content)
    return {
        "path": path,
        "created": not existed,
        "previous_lines": previous_lines,
        "new_lines": len(content.splitlines()),
    }


def replace_in_file(ctx: ToolContext, path: str, old: str, new: str) -> dict[str, Any]:
    """Replace an exact snippet. The match must be unique.

    Requiring uniqueness turns an ambiguous edit into a loud failure instead of a
    silent change to the wrong occurrence — the most common way automated edits
    corrupt a file.
    """
    resolved = resolve_in_workspace(ctx.workspace, path)
    if not resolved.is_file():
        raise ToolError(f"not a file: {path}", path=path)
    if not old:
        raise ToolError("`old` must not be empty; use write_file to create a file")

    content = resolved.read_text(encoding="utf-8", errors="replace")
    occurrences = content.count(old)
    if occurrences == 0:
        raise ToolError("snippet not found; read the file again and match it exactly", path=path)
    if occurrences > 1:
        raise ToolError(
            f"snippet appears {occurrences} times; include more context to make it unique",
            path=path,
            occurrences=occurrences,
        )

    ctx.executor.write_file(path, content.replace(old, new, 1))
    return {"path": path, "replaced": True, "lines_removed": old.count("\n") + 1,
            "lines_added": new.count("\n") + 1}


def apply_patch(ctx: ToolContext, patch: str) -> dict[str, Any]:
    if not patch.strip():
        raise ToolError("patch is empty")

    patch_path = ctx.workspace / ".yukti-patch.diff"
    patch_path.write_text(patch if patch.endswith("\n") else patch + "\n", encoding="utf-8")
    try:
        check = ctx.executor.run(["git", "apply", "--check", ".yukti-patch.diff"])
        if check.exit_code != 0:
            raise ToolError("patch does not apply cleanly", stderr=check.stderr.strip()[:500])
        result = ctx.executor.run(["git", "apply", ".yukti-patch.diff"])
        if result.exit_code != 0:
            raise ToolError("patch application failed", stderr=result.stderr.strip()[:500])
    finally:
        patch_path.unlink(missing_ok=True)

    return {"applied": True}
