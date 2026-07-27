"""End-to-end gate for the checked-in electrical benchmark baseline."""

from pathlib import Path

from circuit_weaver.benchmark_baseline import (
    assert_benchmark_baseline,
    load_benchmark_baseline,
)
from circuit_weaver.benchmark_runner import run_benchmarks

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_electrical_benchmark_does_not_regress_from_checked_in_baseline():
    current = run_benchmarks(REPO_ROOT / "benchmarks" / "electrical")
    baseline = load_benchmark_baseline(REPO_ROOT / "benchmarks" / "baseline.json")

    assert current["fixture_count"] == baseline["fixture_count"]
    assert_benchmark_baseline(current, baseline)
