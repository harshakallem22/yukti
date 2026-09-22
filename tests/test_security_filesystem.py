"""Security tests 1-4: the filesystem jail.

These map to docs/architecture/security-boundaries.md §8.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from core.errors import PathTraversalError
from guardrails.filesystem import resolve_in_workspace

pytestmark = pytest.mark.security


@pytest.mark.parametrize(
    "path",
    [
        "../../../../etc/passwd",
        "../outside.txt",
        "src/../../escape.txt",
        "./../../etc/hosts",
    ],
)
def test_read_outside_workspace_rejected(workspace: Path, path: str) -> None:
    with pytest.raises(PathTraversalError):
        resolve_in_workspace(workspace, path)


def test_symlink_escape_rejected(workspace: Path) -> None:
    """A symlink inside the workspace pointing out of it must not be a way out.

    This is the case a string-normalising path check silently allows.
    """
    (workspace / "escape").symlink_to("/etc")
    with pytest.raises(PathTraversalError):
        resolve_in_workspace(workspace, "escape/passwd")


def test_symlinked_workspace_root_still_works(tmp_path: Path) -> None:
    """Resolving both sides must not break when the workspace itself is behind a
    symlink — macOS temp dirs are (/var -> /private/var)."""
    real = tmp_path / "real"
    real.mkdir()
    (real / "file.txt").write_text("ok")
    link = tmp_path / "link"
    link.symlink_to(real)

    resolved = resolve_in_workspace(link, "file.txt")
    assert resolved.read_text() == "ok"


@pytest.mark.parametrize("path", ["/etc/passwd", "/tmp/x", str(Path.home() / ".ssh" / "id_rsa")])
def test_absolute_path_rejected(workspace: Path, path: str) -> None:
    with pytest.raises(PathTraversalError):
        resolve_in_workspace(workspace, path)


@pytest.mark.parametrize(
    "path",
    [
        ".ssh/id_rsa",
        ".git/config",
        ".git/hooks/pre-commit",
        ".env",
        "nested/.aws/credentials",
        "certs/server.pem",
        "id_rsa",
    ],
)
def test_denylisted_paths_rejected(workspace: Path, path: str) -> None:
    with pytest.raises(PathTraversalError):
        resolve_in_workspace(workspace, path)


def test_nul_byte_rejected(workspace: Path) -> None:
    with pytest.raises(PathTraversalError):
        resolve_in_workspace(workspace, "src/service.py\x00.txt")


def test_ordinary_paths_allowed(workspace: Path) -> None:
    resolved = resolve_in_workspace(workspace, "src/service.py")
    assert resolved.is_file()
    assert str(resolved).startswith(str(workspace.resolve()))


def test_new_file_path_allowed(workspace: Path) -> None:
    """Writes target files that do not exist yet; resolution must still work."""
    resolved = resolve_in_workspace(workspace, "src/brand_new.py")
    assert not resolved.exists()
    assert resolved.parent == (workspace / "src").resolve()


def test_source_repository_never_modified(workspace: Path) -> None:
    """Security test 15: after provisioning and editing a workspace, the origin
    repository is untouched."""
    from sandbox.workspace import provision_workspace

    clone = provision_workspace(workspace, workspace.parent / "workspaces", "run-1")
    (clone / "src" / "service.py").write_text("MUTATED")

    status = subprocess.run(
        ["git", "status", "--porcelain"], cwd=workspace, capture_output=True, text=True, check=True
    )
    assert status.stdout.strip() == "", "origin repository must remain clean"
    assert (workspace / "src" / "service.py").read_text() != "MUTATED"
