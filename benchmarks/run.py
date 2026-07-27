#!/usr/bin/env python3
"""Run the versioned electrical validation benchmark corpus."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from circuit_weaver.benchmark_baseline import assert_benchmark_baseline, load_benchmark_baseline  # noqa: E402
from circuit_weaver.benchmark_runner import (  # noqa: E402
    render_json,
    render_scorecard_json,
    render_scorecard_summary,
    run_benchmarks,
)
from circuit_weaver.finding_contract import load_suppressions  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=REPO_ROOT / "benchmarks" / "electrical")
    parser.add_argument("--output", type=Path, help="write JSON report to this file instead of stdout")
    parser.add_argument(
        "--summary-output",
        type=Path,
        help="write the human-readable scorecard summary to this file",
    )
    parser.add_argument(
        "--scorecard-output",
        type=Path,
        help="write the deterministic committed scorecard JSON to this file",
    )
    parser.add_argument(
        "--check-baseline",
        action="store_true",
        help="fail when per-rule or per-domain precision/recall regresses",
    )
    parser.add_argument(
        "--baseline",
        type=Path,
        default=REPO_ROOT / "benchmarks" / "baseline.json",
        help="versioned baseline used with --check-baseline",
    )
    parser.add_argument(
        "--suppressions",
        type=Path,
        default=REPO_ROOT / "benchmarks" / "electrical" / "suppressions.json",
        help="versioned suppressions validated by the release scorecard gate",
    )
    args = parser.parse_args(argv)
    # Suppressions are independently validated before scoring.  The finding
    # contract marks matching issues rather than filtering them, so their
    # expected/actual counts remain in benchmark denominators.
    suppressions = load_suppressions(args.suppressions)
    result = run_benchmarks(args.root)
    result["suppression_count"] = len(suppressions)
    report = render_json(result)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(report, encoding="utf-8")
    else:
        sys.stdout.write(report)
    if args.summary_output:
        args.summary_output.parent.mkdir(parents=True, exist_ok=True)
        args.summary_output.write_text(render_scorecard_summary(result), encoding="utf-8")
    if args.scorecard_output:
        args.scorecard_output.parent.mkdir(parents=True, exist_ok=True)
        args.scorecard_output.write_text(render_scorecard_json(result), encoding="utf-8")
    if args.check_baseline:
        assert_benchmark_baseline(result, load_benchmark_baseline(args.baseline))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
