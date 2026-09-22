"""Command policy.

Commands are argv lists, never strings, and are never run through a shell. That
removes `;`, `&&`, backticks, `$()` and globbing as an injection surface at the
type level, so this module only has to reason about the program and its arguments.

Classification is allowlist-first: anything unrecognised requires approval. A
blocklist is only a list of the attacks you already thought of.
"""

from __future__ import annotations

import re
from pathlib import PurePosixPath

from guardrails.policy import ActionClass, Decision, RiskLevel

# Never executed, in any risk mode. Shells and interpreters-with-inline-code are
# here because they re-open the injection surface that argv lists closed.
BLOCKED_BINARIES = frozenset(
    {
        "sh", "bash", "zsh", "fish", "csh", "ksh", "eval", "exec", "source",
        "sudo", "su", "doas", "chsh", "passwd",
        "rm", "rmdir", "mv", "dd", "mkfs", "shred", "truncate",
        "chmod", "chown", "chgrp", "chflags",
        "curl", "wget", "nc", "ncat", "netcat", "telnet", "ftp", "rsync",
        "ssh", "scp", "sftp", "ssh-keygen", "ssh-add",
        "docker", "podman", "kubectl", "systemctl", "launchctl", "service",
        "crontab", "at", "kill", "killall", "pkill", "shutdown", "reboot", "halt",
        "brew", "apt", "apt-get", "yum", "dnf", "pacman", "snap",
        "env", "printenv", "export",
    }
)

# Exact argv prefixes that may run without approval.
SAFE_PREFIXES: tuple[tuple[str, ...], ...] = (
    ("pytest",),
    ("python", "-m", "pytest"),
    ("python3", "-m", "pytest"),
    ("python", "-m", "unittest"),
    ("python3", "-m", "unittest"),
    ("npm", "test"),
    ("npm", "run", "test"),
    ("npm", "run", "lint"),
    ("npm", "run", "build"),
    ("npm", "run", "typecheck"),
    ("npx", "vitest", "run"),
    ("npx", "tsc", "--noEmit"),
    ("ruff", "check"),
    ("mypy",),
)

SAFE_GIT_SUBCOMMANDS = frozenset({"status", "diff", "log", "show", "rev-parse", "ls-files"})
BLOCKED_GIT_SUBCOMMANDS = frozenset({"push", "remote", "config", "clean", "gc", "filter-branch"})


def _matches_prefix(argv: list[str], prefix: tuple[str, ...]) -> bool:
    return len(argv) >= len(prefix) and tuple(argv[: len(prefix)]) == prefix


def _classify_git(argv: list[str]) -> Decision:
    if len(argv) < 2:
        return Decision(ActionClass.REQUIRES_APPROVAL, "bare git invocation", RiskLevel.MEDIUM)
    sub = argv[1]
    if sub in BLOCKED_GIT_SUBCOMMANDS:
        return Decision(ActionClass.BLOCKED, f"git {sub} is blocked", RiskLevel.HIGH)
    if sub == "reset" and "--hard" in argv:
        return Decision(ActionClass.BLOCKED, "git reset --hard destroys work", RiskLevel.HIGH)
    if sub in SAFE_GIT_SUBCOMMANDS:
        return Decision(ActionClass.SAFE, f"git {sub} is read-only")
    return Decision(
        ActionClass.REQUIRES_APPROVAL, f"git {sub} mutates repository state", RiskLevel.MEDIUM
    )


def _is_python(program: str) -> bool:
    # Absolute interpreter paths are normal here: test commands use the running
    # interpreter, so the basename may be `python`, `python3` or `python3.12`.
    return bool(re.fullmatch(r"python(3(\.\d+)?)?", program))


def _classify_python(argv: list[str]) -> Decision:
    # `python -c` is an arbitrary-code primitive equivalent to a shell.
    if "-c" in argv:
        return Decision(ActionClass.BLOCKED, "python -c executes arbitrary code", RiskLevel.HIGH)
    normalised = ["python", *argv[1:]]
    for prefix in SAFE_PREFIXES:
        if _matches_prefix(normalised, prefix):
            return Decision(ActionClass.SAFE, f"allowlisted: {' '.join(prefix)}")
    return Decision(
        ActionClass.REQUIRES_APPROVAL, "unrecognised python invocation", RiskLevel.MEDIUM
    )


def classify_command(argv: list[str]) -> Decision:
    if not argv or not argv[0]:
        return Decision(ActionClass.BLOCKED, "empty command", RiskLevel.HIGH)

    program = PurePosixPath(argv[0]).name

    if program in BLOCKED_BINARIES:
        return Decision(ActionClass.BLOCKED, f"'{program}' is on the blocked list", RiskLevel.HIGH)

    if program == "git":
        return _classify_git(argv)

    if _is_python(program):
        return _classify_python(argv)

    if program in {"pip", "pip3"} or _matches_prefix(argv, ("npm", "install")):
        return Decision(
            ActionClass.REQUIRES_APPROVAL,
            "installing packages runs third-party code",
            RiskLevel.HIGH,
        )

    normalised = [program, *argv[1:]]
    for prefix in SAFE_PREFIXES:
        if _matches_prefix(normalised, prefix):
            return Decision(ActionClass.SAFE, f"allowlisted: {' '.join(prefix)}")

    return Decision(
        ActionClass.REQUIRES_APPROVAL,
        f"'{program}' is not on the command allowlist",
        RiskLevel.MEDIUM,
    )
