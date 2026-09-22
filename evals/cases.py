"""Benchmark case loading.

Cases live as JSON in `evals/datasets/` so a change to a case is a reviewable
diff. Each case is content-hashed when it runs: editing a case without recording
its hash would silently invalidate every historical comparison.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
DATASET_DIR = REPO_ROOT / "evals" / "datasets"
BENCHMARK_DIR = REPO_ROOT / "benchmarks"


@dataclass(frozen=True)
class EvalCase:
    id: str
    suite: str
    title: str
    benchmark: str
    issue: dict[str, Any]
    expected_files: list[str]
    acceptable_files: list[str]
    expected_root_cause: str
    forbidden_actions: list[str]
    hidden_tests: str
    content_hash: str
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def repo_path(self) -> Path:
        return BENCHMARK_DIR / self.benchmark / "repo"

    @property
    def hidden_tests_path(self) -> Path:
        return BENCHMARK_DIR / self.benchmark / self.hidden_tests


def _hash(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()[:16]


def load_case(path: Path) -> EvalCase:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return EvalCase(
        id=payload["id"],
        suite=payload.get("suite", "baseline"),
        title=payload["title"],
        benchmark=payload["benchmark"],
        issue=payload["issue"],
        expected_files=payload.get("expected_files", []),
        acceptable_files=payload.get("acceptable_files", payload.get("expected_files", [])),
        expected_root_cause=payload.get("expected_root_cause", ""),
        forbidden_actions=payload.get("forbidden_actions", []),
        hidden_tests=payload.get("hidden_tests", ""),
        content_hash=_hash(payload),
        raw=payload,
    )


def load_suite(suite: str) -> list[EvalCase]:
    cases = [load_case(path) for path in sorted(DATASET_DIR.glob("*.json"))]
    selected = [case for case in cases if suite in {"all", case.suite}]
    if not selected:
        raise ValueError(f"no cases found for suite '{suite}'")
    return selected


def load_one(case_id: str) -> EvalCase:
    for case in (load_case(path) for path in sorted(DATASET_DIR.glob("*.json"))):
        if case.id == case_id:
            return case
    raise ValueError(f"no case with id '{case_id}'")
