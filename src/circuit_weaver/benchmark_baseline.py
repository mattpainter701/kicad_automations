"""Precision/recall baseline comparison for electrical benchmark runs.

This module intentionally has no dependency on the benchmark runner.  The
runner supplies one deterministic JSON-compatible result mapping, while this
module compares only the configured per-rule and per-domain precision/recall
metrics. Unsupported counts are retained for reporting, but aggregate pass
totals and unsupported counts are deliberately not part of this gate.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

BASELINE_SCHEMA_VERSION = 1
RULE_ID_PATTERN = re.compile(r"CW-[A-Z0-9]+-\d{3}$")
METRICS = ("precision", "recall")
UNSUPPORTED_METRIC = "unsupported"
SCOPES = ("rules", "domains")
_COVERAGE_STATUSES = frozenset({"scored", "unsupported"})


@dataclass(frozen=True)
class BenchmarkRegression:
    """One configured metric that fell below its allowed baseline budget."""

    scope: str
    identifier: str
    metric: str
    baseline: float
    current: float
    allowed_drop: float

    @property
    def drop(self) -> float:
        return self.baseline - self.current


class BenchmarkBaselineError(ValueError):
    """The checked-in baseline or current result does not meet the contract."""


class BenchmarkRegressionError(AssertionError):
    """A configured precision or recall regression was detected."""


def load_benchmark_baseline(path: Path) -> dict[str, Any]:
    """Load and validate a JSON baseline artifact from ``benchmarks/baseline.json``."""

    try:
        baseline = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise BenchmarkBaselineError(f"could not read benchmark baseline: {path}") from exc
    except json.JSONDecodeError as exc:
        raise BenchmarkBaselineError(f"invalid benchmark baseline JSON: {path}") from exc
    validate_benchmark_baseline(baseline)
    return baseline


def validate_benchmark_baseline(baseline: Mapping[str, Any]) -> None:
    """Validate the versioned baseline artifact's narrow frozen contract."""

    if baseline.get("schema_version") != BASELINE_SCHEMA_VERSION:
        raise BenchmarkBaselineError("unsupported benchmark baseline schema_version")
    _validate_budget(baseline.get("regression_budget", {}), "regression_budget")
    if not any(scope in baseline for scope in SCOPES):
        raise BenchmarkBaselineError("baseline must contain rules or domains metrics")
    for scope in SCOPES:
        entries = baseline.get(scope, {})
        if not isinstance(entries, Mapping):
            raise BenchmarkBaselineError(f"baseline {scope} must be a mapping")
        for identifier, metrics in entries.items():
            if not isinstance(identifier, str) or not identifier:
                raise BenchmarkBaselineError(f"baseline {scope} identifier must be non-empty")
            if scope == "rules" and not RULE_ID_PATTERN.fullmatch(identifier):
                raise BenchmarkBaselineError(f"invalid rule ID: {identifier!r}")
            _validate_metrics(metrics, f"baseline {scope}.{identifier}")
            _validate_budget(metrics.get("regression_budget", {}), f"baseline {scope}.{identifier}")
    coverage = baseline.get("coverage")
    if coverage is not None:
        if not isinstance(coverage, Mapping) or not coverage:
            raise BenchmarkBaselineError("baseline coverage must be a non-empty mapping")
        for rule_id, status in coverage.items():
            if not isinstance(rule_id, str) or not RULE_ID_PATTERN.fullmatch(rule_id):
                raise BenchmarkBaselineError(f"invalid coverage rule ID: {rule_id!r}")
            if status not in _COVERAGE_STATUSES:
                raise BenchmarkBaselineError(f"baseline coverage.{rule_id} must be scored or unsupported")
    aggregate = baseline.get("aggregate")
    if aggregate is not None:
        if not isinstance(aggregate, Mapping):
            raise BenchmarkBaselineError("baseline aggregate must be a mapping")
        for metric in METRICS:
            value = aggregate.get(f"minimum_{metric}")
            if not isinstance(value, (int, float)) or isinstance(value, bool) or not 0 <= value <= 1:
                raise BenchmarkBaselineError(f"baseline aggregate.minimum_{metric} must be a number from 0 to 1")


def compare_benchmark_baseline(current: Mapping[str, Any], baseline: Mapping[str, Any]) -> list[BenchmarkRegression]:
    """Return configured precision/recall regressions in deterministic order.

    An entry's own ``regression_budget`` overrides the baseline-wide budget.
    A missing metric is malformed benchmark output, rather than evidence that a
    pass-count changed.  Metrics without an explicit non-negative budget are
    not gated.
    """

    validate_benchmark_baseline(baseline)
    regressions: list[BenchmarkRegression] = []
    default_budget = baseline.get("regression_budget", {})
    for scope in SCOPES:
        expected_entries = baseline.get(scope, {})
        if not expected_entries:
            continue
        actual_entries = current.get(scope)
        if not isinstance(actual_entries, Mapping):
            raise BenchmarkBaselineError(f"current benchmark result missing {scope} metrics")
        for identifier in sorted(expected_entries):
            expected = expected_entries[identifier]
            actual = actual_entries.get(identifier)
            if not isinstance(actual, Mapping):
                raise BenchmarkBaselineError(f"current benchmark result missing {scope}.{identifier}")
            _validate_metrics(actual, f"current {scope}.{identifier}")
            budget = {**default_budget, **expected.get("regression_budget", {})}
            for metric in METRICS:
                if metric not in budget:
                    continue
                allowed_drop = budget[metric]
                baseline_value = expected[metric]
                current_value = actual[metric]
                if baseline_value - current_value > allowed_drop:
                    regressions.append(
                        BenchmarkRegression(
                            scope=scope,
                            identifier=identifier,
                            metric=metric,
                            baseline=baseline_value,
                            current=current_value,
                            allowed_drop=allowed_drop,
                        )
                    )
    return regressions


def assert_benchmark_baseline(current: Mapping[str, Any], baseline: Mapping[str, Any]) -> None:
    """Raise only when a configured precision/recall regression occurs."""

    regressions = compare_benchmark_baseline(current, baseline)
    if regressions:
        details = "; ".join(
            f"{item.scope}.{item.identifier} {item.metric}: "
            f"{item.current:.3f} < {item.baseline:.3f} - {item.allowed_drop:.3f}"
            for item in regressions
        )
        raise BenchmarkRegressionError(f"benchmark precision/recall regression: {details}")
    _assert_coverage_and_aggregate(current, baseline)


def _assert_coverage_and_aggregate(current: Mapping[str, Any], baseline: Mapping[str, Any]) -> None:
    """Fail closed when coverage inventory or supported aggregate drifts."""

    expected_coverage = baseline.get("coverage")
    if expected_coverage is not None:
        actual_coverage = current.get("coverage")
        if not isinstance(actual_coverage, Mapping):
            raise BenchmarkBaselineError("current benchmark result missing coverage")
        actual_statuses = {
            rule_id: item.get("status") if isinstance(item, Mapping) else None
            for rule_id, item in actual_coverage.items()
        }
        if dict(expected_coverage) != actual_statuses:
            raise BenchmarkRegressionError(
                "benchmark coverage changed; every registered rule must remain scored or explicitly unsupported"
            )
    expected_aggregate = baseline.get("aggregate")
    if expected_aggregate is not None:
        actual_aggregate = current.get("aggregate")
        if not isinstance(actual_aggregate, Mapping):
            raise BenchmarkBaselineError("current benchmark result missing aggregate")
        failures = []
        for metric in METRICS:
            minimum = expected_aggregate[f"minimum_{metric}"]
            value = actual_aggregate.get(metric)
            if not isinstance(value, (int, float)) or value < minimum:
                failures.append(f"{metric} {value!r} < {minimum:.3f}")
        if failures:
            raise BenchmarkRegressionError("benchmark supported aggregate below release floor: " + "; ".join(failures))


def _validate_metrics(metrics: Any, location: str) -> None:
    if not isinstance(metrics, Mapping):
        raise BenchmarkBaselineError(f"{location} must be a mapping")
    for metric in METRICS:
        value = metrics.get(metric)
        if not isinstance(value, (int, float)) or isinstance(value, bool) or not 0 <= value <= 1:
            raise BenchmarkBaselineError(f"{location}.{metric} must be a number from 0 to 1")
    unsupported = metrics.get(UNSUPPORTED_METRIC)
    if unsupported is not None and (
        not isinstance(unsupported, int) or isinstance(unsupported, bool) or unsupported < 0
    ):
        raise BenchmarkBaselineError(f"{location}.unsupported must be a non-negative integer")


def _validate_budget(budget: Any, location: str) -> None:
    if not isinstance(budget, Mapping):
        raise BenchmarkBaselineError(f"{location} must be a mapping")
    unknown = set(budget) - set(METRICS)
    if unknown:
        raise BenchmarkBaselineError(f"{location} has unknown metric budget(s): {sorted(unknown)}")
    for metric, value in budget.items():
        if not isinstance(value, (int, float)) or isinstance(value, bool) or value < 0:
            raise BenchmarkBaselineError(f"{location}.{metric} must be a non-negative number")
