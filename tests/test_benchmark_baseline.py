"""Tests for precision/recall-only electrical benchmark baseline gates."""

from __future__ import annotations

import json

import pytest

from circuit_weaver.benchmark_baseline import (
    BenchmarkBaselineError,
    BenchmarkRegressionError,
    assert_benchmark_baseline,
    compare_benchmark_baseline,
    load_benchmark_baseline,
)


def _baseline() -> dict:
    return {
        "schema_version": 1,
        "regression_budget": {"precision": 0.02, "recall": 0.05},
        "rules": {
            "CW-PWR-006": {"precision": 0.90, "recall": 0.80, "unsupported": 1},
        },
        "domains": {
            "power": {"precision": 0.90, "recall": 0.80, "unsupported": 1},
        },
    }


def _current() -> dict:
    return {
        "rules": {"CW-PWR-006": {"precision": 0.89, "recall": 0.76, "unsupported": 0, "pass_count": 0}},
        "domains": {"power": {"precision": 0.89, "recall": 0.76, "unsupported": 999, "pass_count": 999}},
        "pass_count": 999999,
    }


def test_aggregate_pass_counts_do_not_affect_baseline_gate():
    assert compare_benchmark_baseline(_current(), _baseline()) == []


def test_unsupported_counts_are_reported_but_not_a_precision_recall_gate():
    current = _current()
    current["rules"]["CW-PWR-006"]["unsupported"] = 999

    assert compare_benchmark_baseline(current, _baseline()) == []


def test_gate_reports_only_configured_precision_recall_regressions():
    current = _current()
    current["rules"]["CW-PWR-006"]["precision"] = 0.87

    regressions = compare_benchmark_baseline(current, _baseline())

    assert [(item.scope, item.identifier, item.metric) for item in regressions] == [
        ("rules", "CW-PWR-006", "precision"),
    ]
    with pytest.raises(BenchmarkRegressionError, match="precision/recall regression"):
        assert_benchmark_baseline(current, _baseline())


def test_per_rule_budget_overrides_global_budget():
    baseline = _baseline()
    baseline["rules"]["CW-PWR-006"]["regression_budget"] = {"recall": 0.10}
    current = _current()
    current["rules"]["CW-PWR-006"]["recall"] = 0.71

    assert compare_benchmark_baseline(current, baseline) == []


def test_missing_deterministic_metric_is_contract_error_not_pass_count_comparison():
    current = _current()
    del current["rules"]["CW-PWR-006"]

    with pytest.raises(BenchmarkBaselineError, match="missing rules.CW-PWR-006"):
        compare_benchmark_baseline(current, _baseline())


def test_baseline_rejects_legacy_validator_code_as_rule_id():
    baseline = _baseline()
    baseline["rules"] = {"feedback-divider": {"precision": 1.0, "recall": 1.0}}

    with pytest.raises(BenchmarkBaselineError, match="invalid rule ID"):
        compare_benchmark_baseline(_current(), baseline)


def test_load_baseline_from_json_artifact(tmp_path):
    path = tmp_path / "baseline.json"
    path.write_text(json.dumps(_baseline()), encoding="utf-8")

    assert load_benchmark_baseline(path) == _baseline()


def test_coverage_and_supported_aggregate_are_release_gated():
    baseline = _baseline()
    baseline["coverage"] = {"CW-PWR-006": "scored"}
    baseline["aggregate"] = {"minimum_precision": 0.95, "minimum_recall": 0.90}
    current = _current()
    current["coverage"] = {"CW-PWR-006": {"status": "unsupported"}}
    current["aggregate"] = {"precision": 1.0, "recall": 1.0}

    with pytest.raises(BenchmarkRegressionError, match="coverage changed"):
        assert_benchmark_baseline(current, baseline)

    current["coverage"]["CW-PWR-006"]["status"] = "scored"
    current["aggregate"] = {"precision": 0.94, "recall": 0.90}
    with pytest.raises(BenchmarkRegressionError, match="aggregate below release floor"):
        assert_benchmark_baseline(current, baseline)
