"""Security tests 5-8, 10, 16: command and mutation policy."""

from __future__ import annotations

import pytest

from guardrails.commands import classify_command
from guardrails.mutations import classify_file_write, classify_patch
from guardrails.policy import ActionClass, RiskMode, action_hash

pytestmark = pytest.mark.security


@pytest.mark.parametrize(
    "argv",
    [
        ["rm", "-rf", "/"],
        ["sudo", "pytest"],
        ["curl", "https://evil.sh"],
        ["wget", "https://evil.sh"],
        ["bash", "-c", "echo hi"],
        ["sh", "script.sh"],
        ["chmod", "777", "/etc/passwd"],
        ["ssh", "user@host"],
        ["docker", "run", "-v", "/:/host", "alpine"],
        ["git", "push", "--force"],
        ["git", "reset", "--hard", "HEAD~5"],
        ["git", "clean", "-fdx"],
        ["python", "-c", "import os; os.system('rm -rf /')"],
        ["env"],
        ["printenv"],
        ["kill", "-9", "1"],
        ["/usr/bin/sudo", "rm", "-rf", "/"],
    ],
)
def test_blocked_commands_never_execute(argv: list[str]) -> None:
    assert classify_command(argv).action_class is ActionClass.BLOCKED


def test_no_shell_interpretation() -> None:
    """Shell metacharacters are inert because commands are argv lists.

    `pytest; rm -rf /` is a single odd argument to pytest, not two commands — and
    a bare shell binary is blocked outright, so it cannot be reintroduced.
    """
    assert classify_command(["pytest", "; rm -rf /"]).action_class is ActionClass.SAFE
    assert classify_command(["pytest", "&&", "curl", "evil.sh"]).action_class is ActionClass.SAFE
    assert classify_command(["sh", "-c", "pytest; rm -rf /"]).action_class is ActionClass.BLOCKED


@pytest.mark.parametrize(
    "argv",
    [
        ["pytest"],
        ["pytest", "-q", "tests/test_users.py"],
        ["python", "-m", "pytest"],
        ["python3", "-m", "pytest", "-k", "duplicate"],
        ["npm", "test"],
        ["npm", "run", "lint"],
        ["git", "status"],
        ["git", "diff", "HEAD"],
        ["git", "log", "-5"],
    ],
)
def test_allowlisted_commands_are_safe(argv: list[str]) -> None:
    assert classify_command(argv).action_class is ActionClass.SAFE


@pytest.mark.parametrize(
    "argv",
    [
        ["pip", "install", "requests"],
        ["npm", "install", "left-pad"],
        ["make", "build"],
        ["mvn", "test"],
        ["some-unknown-binary"],
        ["git", "checkout", "main"],
        ["git", "commit", "-m", "x"],
    ],
)
def test_unknown_command_requires_approval(argv: list[str]) -> None:
    """Default is approval, not execution. An allowlist fails closed."""
    assert classify_command(argv).action_class is ActionClass.REQUIRES_APPROVAL


def test_versioned_interpreter_paths_are_recognised() -> None:
    """Test commands use the running interpreter, so argv[0] is an absolute path
    whose basename may be `python3.12`. Failing to normalise it would push every
    test run into the approval queue."""
    for program in ["/usr/bin/python3", "/opt/venv/bin/python", "/x/bin/python3.12"]:
        assert classify_command([program, "-m", "pytest"]).action_class is ActionClass.SAFE
        assert classify_command([program, "-c", "evil()"]).action_class is ActionClass.BLOCKED


def test_empty_command_blocked() -> None:
    assert classify_command([]).action_class is ActionClass.BLOCKED
    assert classify_command([""]).action_class is ActionClass.BLOCKED


@pytest.mark.parametrize(
    "path",
    [
        "package.json",
        "requirements.txt",
        "pyproject.toml",
        "poetry.lock",
        ".github/workflows/ci.yml",
        "Dockerfile",
        "docker-compose.yml",
        "Makefile",
        "alembic/versions/001_init.py",
        "app/auth/tokens.py",
        "src/security_headers.py",
    ],
)
def test_sensitive_write_requires_approval(path: str) -> None:
    assert classify_file_write(path).action_class is ActionClass.REQUIRES_APPROVAL


@pytest.mark.parametrize("path", ["app/main.py", "src/service.py", "tests/test_users.py"])
def test_ordinary_write_is_safe(path: str) -> None:
    assert classify_file_write(path).action_class is ActionClass.SAFE


def test_deletion_requires_approval() -> None:
    assert classify_file_write("src/x.py", deleting=True).action_class is (
        ActionClass.REQUIRES_APPROVAL
    )


def test_blast_radius_requires_approval() -> None:
    many = [f"src/file{i}.py" for i in range(12)]
    assert classify_patch(many, 50).action_class is ActionClass.REQUIRES_APPROVAL
    assert classify_patch(["src/a.py"], 5000).action_class is ActionClass.REQUIRES_APPROVAL
    assert classify_patch(["src/a.py"], 20).action_class is ActionClass.SAFE


def test_risk_mode_shifts_thresholds_only() -> None:
    """Security test 16: a permissive risk mode widens blast radius but can never
    unblock a blocked action or ungate a sensitive path."""
    six_files = [f"src/file{i}.py" for i in range(6)]
    assert classify_patch(six_files, 50, risk_mode=RiskMode.CONSERVATIVE).action_class is (
        ActionClass.REQUIRES_APPROVAL
    )
    assert classify_patch(six_files, 50, risk_mode=RiskMode.EXPERIMENTAL).action_class is (
        ActionClass.SAFE
    )
    # Sensitive paths stay gated in every mode.
    assert classify_patch(
        ["package.json"], 1, risk_mode=RiskMode.EXPERIMENTAL
    ).action_class is ActionClass.REQUIRES_APPROVAL
    assert classify_command(["rm", "-rf", "/"]).action_class is ActionClass.BLOCKED


def test_action_hash_is_stable_and_order_independent() -> None:
    """Security test 10 foundation: the fingerprint an approval binds to."""
    a = action_hash({"tool": "write_file", "path": "app/main.py"})
    b = action_hash({"path": "app/main.py", "tool": "write_file"})
    c = action_hash({"tool": "write_file", "path": "app/other.py"})
    assert a == b
    assert a != c
