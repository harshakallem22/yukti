#!/usr/bin/env python
"""Verify every benchmark case is well-formed.

A benchmark whose hidden tests already pass on the broken repository silently
inflates every future task-success number, and nothing else in the pipeline would
catch it. This runs in CI for that reason.

Checks per case:
  1. the visible suite passes   (the bug is not already covered)
  2. the hidden suite fails     (the bug is real)
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from evals.cases import load_suite  # noqa: E402


def _pytest(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603
        [sys.executable, "-m", "pytest", "-q", "--no-header", *args],
        cwd=cwd, capture_output=True, text=True, timeout=300, check=False,
    )


def main() -> int:
    cases = load_suite("all")
    failures: list[str] = []

    for case in cases:
        repo = case.repo_path
        if not repo.is_dir():
            failures.append(f"{case.id}: repository missing at {repo}")
            continue

        visible = _pytest(repo)
        if visible.returncode != 0:
            failures.append(
                f"{case.id}: visible suite must pass on the broken repo\n"
                f"{visible.stdout[-600:]}"
            )

        hidden_path = case.hidden_tests_path
        if not hidden_path.is_file():
            failures.append(f"{case.id}: hidden tests missing at {hidden_path}")
            continue

        hidden = _pytest(repo, str(hidden_path))
        if hidden.returncode == 0:
            failures.append(
                f"{case.id}: hidden suite PASSES on the broken repo — the bug is "
                f"not reproduced, so this case would grade every run as a success"
            )

        status = "ok" if not failures or not failures[-1].startswith(case.id) else "BAD"
        print(f"  {case.id:<22} visible={'pass' if visible.returncode == 0 else 'FAIL'}  "
              f"hidden={'fail (expected)' if hidden.returncode != 0 else 'PASS (bad)'}  [{status}]")

    print(f"\n{len(cases)} case(s) checked")
    if failures:
        print("\nProblems:", file=sys.stderr)
        for failure in failures:
            print(f"  - {failure}", file=sys.stderr)
        return 1
    print("All benchmarks are well-formed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
