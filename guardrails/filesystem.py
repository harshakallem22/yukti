"""Filesystem jail.

Every path that reaches the filesystem passes through `resolve_in_workspace`.
Tools must not construct paths any other way.
"""

from __future__ import annotations

import fnmatch
from pathlib import Path

from core.errors import PathTraversalError

# Denied anywhere in the tree, even inside the workspace. `.git` is denied for
# direct file access because writing `.git/hooks/*` turns any later `git`
# invocation into arbitrary code execution — a bypass that never touches the
# command allowlist. Git operations go through the git binary instead.
DENIED_COMPONENTS = frozenset({".git", ".ssh", ".aws", ".gnupg", ".docker", ".kube"})
DENIED_NAMES = frozenset({".env", ".netrc", ".npmrc", ".pypirc", ".git-credentials"})
DENIED_PATTERNS = ("id_rsa*", "id_ed25519*", "*.pem", "*.key", "*.p12", "*.keystore")


def _is_denied(relative: Path) -> str | None:
    for part in relative.parts:
        if part in DENIED_COMPONENTS:
            return f"path component '{part}' is denied"
    name = relative.name
    if name in DENIED_NAMES:
        return f"file '{name}' is denied"
    for pattern in DENIED_PATTERNS:
        if fnmatch.fnmatch(name, pattern):
            return f"file '{name}' matches denied pattern '{pattern}'"
    return None


def resolve_in_workspace(workspace_root: Path, user_path: str) -> Path:
    """Resolve `user_path` to a real path proven to lie inside `workspace_root`.

    Symlinks are resolved *before* the containment comparison. Normalising the
    path string first and comparing prefixes is the classic bug: a symlink at
    `workspace/link -> /etc` makes `link/passwd` pass a string check while
    reading a host file.
    """
    if "\x00" in user_path:
        raise PathTraversalError("path contains a NUL byte", path=user_path)

    candidate = Path(user_path)
    if candidate.is_absolute():
        raise PathTraversalError("absolute paths are not permitted", path=user_path)

    root = workspace_root.resolve()
    # Non-strict resolve: works for files that do not exist yet (writes), while
    # still resolving every symlink in the existing prefix.
    real = (root / candidate).resolve()

    if real != root and root not in real.parents:
        raise PathTraversalError(
            "path escapes the workspace boundary", path=user_path, resolved=str(real)
        )

    relative = real.relative_to(root)
    if reason := _is_denied(relative):
        raise PathTraversalError(reason, path=user_path)

    return real
