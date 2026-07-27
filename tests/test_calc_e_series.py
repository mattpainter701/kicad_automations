"""T246.4 E-series policy contracts for immutable calculation records."""

from __future__ import annotations

import json

import pytest

from circuit_weaver.calc import (
    apply_capacitor_selection,
    apply_e_series_selection,
    apply_ratio_preserving_divider_selection,
    emit_calculation_evidence,
    rc_capacitance_for_cutoff,
    rc_resistance_for_cutoff,
    select_e_series,
)
from circuit_weaver.evidence import EvidenceLedger


def _resistance_record(target: str, resistance_ohm: float):
    return rc_resistance_for_cutoff(
        target=target,
        capacitance_f=1e-6,
        cutoff_hz=1 / (2 * 3.141592653589793 * resistance_ohm * 1e-6),
    )


@pytest.mark.parametrize(
    ("series", "value", "expected"),
    [
        ("E6", 6.9, 6.8),
        ("E12", 8.3, 8.2),
        ("E24", 3.25, 3.3),
        ("E96", 10_250, 10_200),
    ],
)
def test_nearest_e_series_selection_is_deterministic_across_supported_series(series, value, expected):
    assert select_e_series(value, series=series) == pytest.approx(expected)


def test_e_series_handles_decades_directions_and_nearest_ties():
    assert select_e_series(1.25, series="E6", direction="nearest") == pytest.approx(1.0)
    assert select_e_series(9.2, series="E12", direction="up") == pytest.approx(10.0)
    assert select_e_series(10.9, series="E12", direction="down") == pytest.approx(10.0)
    assert select_e_series(0.00101, series="E24", direction="up") == pytest.approx(0.0011)


@pytest.mark.parametrize("value", [0, -1, float("nan"), float("inf")])
def test_e_series_rejects_invalid_values_and_policies(value):
    with pytest.raises(ValueError):
        select_e_series(value)
    with pytest.raises(ValueError):
        select_e_series(1.0, series="E48")
    with pytest.raises(ValueError):
        select_e_series(1.0, direction="ratio_preserving")


def test_safe_capacitor_selection_rounds_up_and_does_not_mutate_raw_calculation():
    raw = rc_capacitance_for_cutoff(
        target="param:U1.filter.capacitance",
        resistance_ohm=1_000,
        cutoff_hz=1 / (2 * 3.141592653589793 * 1_040e-9 * 1_000),
    )

    selected = apply_capacitor_selection(raw, series="E24")

    assert raw.chosen_value is None
    assert selected.id == raw.id
    assert selected.raw_result == raw.raw_result
    assert selected.snap_policy is not None and selected.snap_policy.direction == "up"
    assert selected.chosen_value is not None
    assert selected.chosen_value.value >= raw.raw_result.value
    assert selected.chosen_value.value == pytest.approx(1.1e-6)


def test_divider_pair_joint_search_beats_independent_rounding_and_is_immutable():
    top = _resistance_record("param:U1.divider.top", 1_100)
    bottom = _resistance_record("param:U1.divider.bottom", 1_400)
    target_vout = 1 + 1_100 / 1_400
    independent_vout = 1 + select_e_series(1_100, series="E24") / select_e_series(1_400, series="E24")

    selected = apply_ratio_preserving_divider_selection(
        top, bottom, target_vout_v=target_vout, vref_v=1.0, series="E24"
    )

    assert top.chosen_value is None and bottom.chosen_value is None
    assert selected.top.chosen_value is not None and selected.bottom.chosen_value is not None
    assert selected.top.chosen_value.value == pytest.approx(1_200)
    assert selected.bottom.chosen_value.value == pytest.approx(1_500)
    assert abs(selected.realized_vout_v - target_vout) < abs(independent_vout - target_vout)
    assert selected.top.snap_policy is not None
    assert selected.top.snap_policy.direction == "ratio_preserving"
    assert selected.top.margin is not None and selected.top.margin.kind == "vout_error_within_2x_leg_scale"
    assert selected.max_scale_factor == 2.0
    assert (
        apply_ratio_preserving_divider_selection(top, bottom, target_vout_v=target_vout, vref_v=1.0, series="E24")
        == selected
    )


def test_divider_pair_default_scale_window_keeps_feedback_impedance_near_raw_design():
    top = _resistance_record("param:U1.divider.top", 31_250)
    bottom = _resistance_record("param:U1.divider.bottom", 10_000)

    selected = apply_ratio_preserving_divider_selection(top, bottom, target_vout_v=3.3, vref_v=0.8, series="E96")

    assert selected.top.chosen_value is not None and selected.bottom.chosen_value is not None
    assert 15_625 <= selected.top.chosen_value.value <= 62_500
    assert 5_000 <= selected.bottom.chosen_value.value <= 20_000
    assert (selected.top.chosen_value.value, selected.bottom.chosen_value.value) != (357_000, 115_000)
    assert selected.top.margin is not None
    assert "2x_leg_scale" in selected.top.margin.kind


@pytest.mark.parametrize("factor", [0, 0.5, float("nan"), float("inf")])
def test_divider_pair_rejects_invalid_impedance_scale_windows(factor):
    top = _resistance_record("param:U1.divider.top", 1_100)
    bottom = _resistance_record("param:U1.divider.bottom", 1_400)

    with pytest.raises(ValueError, match="max_scale_factor"):
        apply_ratio_preserving_divider_selection(
            top,
            bottom,
            target_vout_v=1 + 1_100 / 1_400,
            vref_v=1.0,
            max_scale_factor=factor,
        )


def test_divider_pair_fails_closed_when_tight_window_has_no_standard_pair():
    top = _resistance_record("param:U1.divider.top", 1_111)
    bottom = _resistance_record("param:U1.divider.bottom", 1_411)

    with pytest.raises(ValueError, match="no E-series divider pair"):
        apply_ratio_preserving_divider_selection(
            top,
            bottom,
            target_vout_v=1 + 1_111 / 1_411,
            vref_v=1.0,
            series="E24",
            max_scale_factor=1.0,
        )


def test_scalar_snap_is_immutable_and_calculation_evidence_serializes_policy_fields():
    raw = _resistance_record("param:U1.filter.resistance", 1_040)
    selected = apply_e_series_selection(raw, series="E24", direction="nearest")

    assert raw.chosen_value is None
    assert selected.id == raw.id
    ledger = EvidenceLedger()
    emitted = emit_calculation_evidence(selected, ledger)
    evidence = ledger.get(emitted.emits_evidence)
    assert evidence is not None
    payload = json.loads(evidence.claim.removeprefix("calculation="))
    assert payload["chosen_value"] == selected.chosen_value.to_dict()
    assert payload["snap_policy"] == selected.snap_policy.to_dict()
    assert payload["margin"] == selected.margin.to_dict()
    resnapped = apply_e_series_selection(emitted, series="E24", direction="up")
    assert resnapped.emits_evidence is None
