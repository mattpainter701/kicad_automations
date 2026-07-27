"""Focused T246 trace contracts for non-switching topology producers."""

from __future__ import annotations

import pytest

from circuit_weaver.ic_data import get_ic_data
from circuit_weaver.subcircuits.topology_builders import (
    build_can_transceiver,
    build_display_driver,
    build_linear_regulator,
    build_protection,
)


def _assert_closed_trace(component, passives) -> None:
    calculations = {record.id: record for record in component.passive_synthesis_calculations}
    evidence = {record.id for record in component.passive_synthesis_evidence}
    for passive in passives:
        assert passive.calculation_id in calculations
        assert passive.selection_policy is not None
        assert passive.confidence is not None
        assert passive.evidence_ids
        assert set(passive.evidence_ids) <= evidence


def test_ldo_caps_prefer_actual_datasheet_metadata_and_fallback_is_explicit():
    sourced = build_linear_regulator(
        get_ic_data("TLV75518"), {"vin": 3.3, "vout": 1.8, "iout": 0.3, "ref": "U1"}
    ).components[0]
    fallback = build_linear_regulator(
        get_ic_data("AMS1117-3.3"), {"vin": 5.0, "vout": 3.3, "iout": 0.5, "ref": "U2"}
    ).components[0]

    _assert_closed_trace(sourced, sourced.bypass_caps)
    _assert_closed_trace(fallback, fallback.bypass_caps)
    assert {cap.selection_policy for cap in sourced.bypass_caps} == {"datasheet"}
    assert {cap.selection_policy for cap in fallback.bypass_caps} == {"bounded_fallback"}
    assert {cap.confidence for cap in fallback.bypass_caps} == {"heuristic"}


def test_ldo_out_of_range_fallback_fails_before_cap_emission():
    ic_data = dict(get_ic_data("AMS1117-3.3"))
    ic_data["cin"] = 1e-3
    with pytest.raises(ValueError, match=r"CW-PSV-002"):
        build_linear_regulator(ic_data, {"vin": 5.0, "vout": 3.3, "iout": 0.5, "ref": "U2"})


def test_ldo_datasheet_minimum_capacitance_snaps_up_safely():
    ic_data = dict(get_ic_data("TLV75518"))
    ic_data["cout"] = 1.04e-6

    component = build_linear_regulator(
        ic_data,
        {"vin": 3.3, "vout": 1.8, "iout": 0.3, "ref": "U4"},
    ).components[0]
    output_cap = next(cap for cap in component.bypass_caps if cap.pin == "COUT")

    assert output_cap.value == "1.1uF"
    assert output_cap.selection_policy == "datasheet"


def test_can_decoupling_termination_and_slope_networks_have_closed_fallback_trace():
    component = build_can_transceiver(
        get_ic_data("SN65HVD230"),
        {"ref": "U7", "termination": True, "slope_control": True},
    ).components[0]

    passives = [*component.bypass_caps, *component.straps]
    _assert_closed_trace(component, passives)
    assert {passive.selection_policy for passive in passives} == {"bounded_fallback"}
    assert {passive.confidence for passive in passives} == {"heuristic"}


def test_protection_device_does_not_claim_a_synthesized_support_network():
    component = build_protection(get_ic_data("SMBJ5.0A"), {"ref": "D5", "protect_net": "VBUS"}).components[0]
    assert component.bypass_caps == []
    assert component.straps == []
    assert component.passive_synthesis_calculations == []


def test_display_reset_pair_has_explicit_bounded_fallback_trace():
    component = build_display_driver(get_ic_data("SSD1306"), {"ref": "U3", "interface": "i2c"}).components[0]
    reset_passives = [
        passive
        for passive in [*component.bypass_caps, *component.straps]
        if passive.role in {"reset_delay", "reset_pullup"}
    ]

    assert len(reset_passives) == 2
    _assert_closed_trace(component, reset_passives)
    _assert_closed_trace(component, [*component.bypass_caps, *component.straps])
    assert {passive.selection_policy for passive in reset_passives} == {"bounded_fallback"}
    assert {passive.confidence for passive in reset_passives} == {"heuristic"}
