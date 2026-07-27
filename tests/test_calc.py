"""Contracts for the pure T246 calculation substrate."""

from __future__ import annotations

import json
import math

import pytest

from circuit_weaver.calc import (
    CalculationInput,
    calculation_id,
    crystal_effective_load,
    crystal_external_load_cap,
    feedback_divider_top,
    feedback_divider_vout,
    lc_cutoff,
    rc_capacitance_for_cutoff,
    rc_cutoff,
    rc_resistance_for_cutoff,
)

TARGET = "param:U1.power.value"


def test_equations_are_exact_and_unit_explicit():
    assert feedback_divider_top(
        target=TARGET, vout_v=3.3, vref_v=1.0, r_bottom_ohm=10_000
    ).raw_result.value == pytest.approx(23_000)
    vout = feedback_divider_vout(target=TARGET, r_top_ohm=23_000, r_bottom_ohm=10_000, vref_v=1.0)
    assert vout.raw_result.value == pytest.approx(3.3)
    assert rc_cutoff(target=TARGET, resistance_ohm=1_000, capacitance_f=1e-6).raw_result.value == pytest.approx(
        1 / (2 * math.pi * 1_000 * 1e-6)
    )
    capacitance = rc_capacitance_for_cutoff(
        target=TARGET, resistance_ohm=1_000, cutoff_hz=1_000
    )
    assert capacitance.raw_result.value == pytest.approx(
        1 / (2 * math.pi * 1_000 * 1_000)
    )
    resistance = rc_resistance_for_cutoff(
        target=TARGET, capacitance_f=1e-6, cutoff_hz=1_000
    )
    assert resistance.raw_result.value == pytest.approx(
        1 / (2 * math.pi * 1e-6 * 1_000)
    )
    assert lc_cutoff(target=TARGET, inductance_h=10e-6, capacitance_f=1e-6).raw_result.value == pytest.approx(
        1 / (2 * math.pi * math.sqrt(10e-6 * 1e-6))
    )
    external_cap = crystal_external_load_cap(target=TARGET, load_capacitance_f=12e-12, stray_capacitance_f=4e-12)
    assert external_cap.raw_result.value == pytest.approx(16e-12)
    effective_load = crystal_effective_load(
        target=TARGET, capacitance_1_f=16e-12, capacitance_2_f=16e-12, stray_capacitance_f=4e-12
    )
    assert effective_load.raw_result.value == pytest.approx(12e-12)


def test_crystal_equations_accept_zero_stray_capacitance():
    external_cap = crystal_external_load_cap(target=TARGET, load_capacitance_f=12e-12, stray_capacitance_f=0)
    assert external_cap.raw_result.value == pytest.approx(24e-12)
    effective_load = crystal_effective_load(
        target=TARGET, capacitance_1_f=24e-12, capacitance_2_f=24e-12, stray_capacitance_f=0
    )
    assert effective_load.raw_result.value == pytest.approx(12e-12)


@pytest.mark.parametrize(
    "call",
    [
        lambda: feedback_divider_top(target=TARGET, vout_v=1.0, vref_v=1.0, r_bottom_ohm=10_000),
        lambda: feedback_divider_vout(target=TARGET, r_top_ohm=0, r_bottom_ohm=10_000, vref_v=1.0),
        lambda: rc_cutoff(target=TARGET, resistance_ohm=float("nan"), capacitance_f=1e-6),
        lambda: rc_capacitance_for_cutoff(target=TARGET, resistance_ohm=0, cutoff_hz=1_000),
        lambda: rc_resistance_for_cutoff(target=TARGET, capacitance_f=1e-6, cutoff_hz=0),
        lambda: lc_cutoff(target=TARGET, inductance_h=1e-6, capacitance_f=0),
        lambda: crystal_external_load_cap(target=TARGET, load_capacitance_f=4e-12, stray_capacitance_f=4e-12),
        lambda: crystal_effective_load(
            target=TARGET, capacitance_1_f=float("inf"), capacitance_2_f=10e-12, stray_capacitance_f=1e-12
        ),
    ],
)
def test_invalid_domains_fail_closed(call):
    with pytest.raises(ValueError):
        call()


def test_calculation_id_is_deterministic_and_insensitive_to_input_order():
    inputs = (
        CalculationInput("vout", 3.3, "V", "EV-DATASHEET-aaaaaaaaaaaa"),
        CalculationInput("vref", 1.0, "V"),
    )
    first = calculation_id(TARGET, "feedback_divider", inputs)
    second = calculation_id(TARGET, "feedback_divider", tuple(reversed(inputs)))
    assert first == second
    assert first.startswith("CALC-FEEDBACK_DIVIDER-")
    assert calculation_id("param:U2.power.value", "feedback_divider", inputs) != first


def test_record_serializes_to_json_with_stable_null_policy_fields():
    record = rc_cutoff(
        target=TARGET,
        resistance_ohm=1_000,
        capacitance_f=1e-6,
        evidence_ids={"resistance_ohm": "EV-DATASHEET-aaaaaaaaaaaa"},
    )
    data = record.to_dict()
    assert data["policy"] == "equation"
    assert data["confidence"] == "single_source"
    assert data["chosen_value"] is None
    assert data["snap_policy"] is None
    assert data["margin"] is None
    assert data["emits_evidence"] is None
    assert data["inputs"][0]["evidence_id"] == "EV-DATASHEET-aaaaaaaaaaaa"
    assert json.loads(json.dumps(data)) == data
