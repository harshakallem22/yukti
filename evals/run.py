"""Evaluation CLI.

    python -m evals.run --suite baseline
    python -m evals.run --case fastapi-bug-001
    python -m evals.run --suite baseline --baseline evals/reports/<file>.json
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from evals import report
from evals.cases import load_one, load_suite
from evals.harness import DemoModeRefused, run_suite


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="evals.run", description="Run Yukti benchmark suites")
    parser.add_argument("--suite", default="baseline", help="suite name, or 'all'")
    parser.add_argument("--case", help="run a single case by id")
    parser.add_argument("--baseline", type=Path, help="previous report JSON to compare against")
    parser.add_argument(
        "--allow-demo",
        action="store_true",
        help="permit the scripted provider (smoke-tests the harness; results are not real metrics)",
    )
    args = parser.parse_args(argv)

    try:
        cases = [load_one(args.case)] if args.case else load_suite(args.suite)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    suite_name = args.case or args.suite
    try:
        payload = run_suite(cases, suite_name, allow_demo=args.allow_demo)
    except DemoModeRefused as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 3

    summary = payload["summary"]
    print()
    print(report.render(suite_name, summary))

    if args.baseline:
        if args.baseline.is_file():
            print(report.compare(summary, report.load_baseline(args.baseline)))
        else:
            print(f"\nbaseline not found: {args.baseline}", file=sys.stderr)

    path = report.save(suite_name, payload)
    print(f"\nReport written to {path}")
    return 0 if summary.get("task_success_rate", 0) > 0 or summary.get("demo_mode") else 1


if __name__ == "__main__":
    raise SystemExit(main())
