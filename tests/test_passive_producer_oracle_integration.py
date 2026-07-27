"""Independent expected-value checks through the actual T246 producers."""

from __future__ import annotations

import pytest

from circuit_weaver.ic_data import get_ic_data
from circuit_weaver.subcircuits.adc import ADCTemplate
from circuit_weaver.subcircuits.crystal_oscillator import CrystalOscillatorTemplate
from circuit_weaver.subcircuits.rs485_transceiver import RS485TransceiverTemplate
from circuit_weaver.subcircuits.topology_builders import (
    build_can_transceiver,
    build_linear_regulator,
    build_switching_regulator,
)
from circuit_weaver.subcircuits.usb_c_connector import USBCConnectorTemplate
from circuit_weaver.validator import (
    _validate_crystal_caps,
    _validate_feedback_dividers,
    _validate_filter_cutoffs,
)


def _chosen(component, passive) -> float:
    record = next(item for item in component.passive_synthesis_calculations if item.id == passive.calculation_id)
    assert record.chosen_value is not None
    return record.chosen_value.value


@pytest.mark.parametrize(
    ("ic_data", "params", "expected_top", "expected_bottom"),
    [
        (
            get_ic_data("AP62300"),
            {"vin": 12.0, "vout": 3.3, "iout": 1.0, "r_fbb": 10e3, "ref": "U1"},
            35.7e3,
            11.5e3,
        ),
        (
            {**get_ic_data("TPS61230A"), "vref": 1.2, "vref_provenance": "independent-oracle"},
            {"vin": 3.3, "vout": 5.0, "iout": 1.0, "r_fbb": 10e3, "ref": "U2"},
            47.5e3,
            15e3,
        ),
    ],
)
def test_switcher_producers_match_reviewed_feedback_pairs(ic_data, params, expected_top, expected_bottom) -> None:
    component = build_switching_regulator(ic_data, params).components[0]
    top = next(item for item in component.straps if item.role == "feedback_top")
    bottom = next(item for item in component.straps if item.role == "feedback_bottom")

    assert _chosen(component, top) == pytest.approx(expected_top)
    assert _chosen(component, bottom) == pytest.approx(expected_bottom)
    assert _validate_feedback_dividers([component]) == []


def test_ldo_producer_safely_rounds_reviewed_minimum_capacitance() -> None:
    component = build_linear_regulator(
        {**get_ic_data("TLV75518"), "cout": 1.04e-6},
        {"vin": 3.3, "vout": 1.8, "iout": 0.3, "ref": "U3"},
    ).components[0]
    output_cap = next(item for item in component.bypass_caps if item.pin == "COUT")

    assert _chosen(component, output_cap) == pytest.approx(1.1e-6)
    assert output_cap.selection_policy == "datasheet"


def test_crystal_and_analog_producers_match_reviewed_equations_and_self_validate() -> None:
    crystal = (
        CrystalOscillatorTemplate()
        .generate({"freq": 12e6, "cl_spec": 12.0, "c_stray": 4e-12, "ref": "Y1"})
        .components[0]
    )
    adc = ADCTemplate().generate({"ref": "U4", "channels": 1, "input_filter_bw": 1591.5494309189535}).components[0]

    assert {_chosen(crystal, cap) for cap in crystal.bypass_caps if cap.role == "load_cap"} == {18e-12}
    assert {_chosen(adc, cap) for cap in adc.bypass_caps if cap.role == "input_filter"} == {100e-9}
    assert _validate_crystal_caps([crystal]) == []
    assert _validate_filter_cutoffs([adc]) == []


def test_usb_can_and_rs485_producers_match_reviewed_interface_values() -> None:
    usb = USBCConnectorTemplate().generate({"role": "device", "ref": "J1"}).components[0]
    can = build_can_transceiver(
        get_ic_data("SN65HVD230"),
        {"termination": True, "ref": "U5"},
    ).components[0]
    rs485 = (
        RS485TransceiverTemplate()
        .generate({"termination": True, "bus_impedance_ohm": 120.0, "failsafe_bias": False, "ref": "U6"})
        .components[0]
    )

    assert {_chosen(usb, item) for item in usb.straps if item.role.startswith("cc_")} == {5.1e3}
    can_legs = [_chosen(can, item) for item in can.straps if item.role == "termination"]
    assert sum(can_legs) == pytest.approx(120.0, rel=0.01)
    rs485_term = next(item for item in rs485.straps if item.role == "termination")
    assert _chosen(rs485, rs485_term) == pytest.approx(120.0)

    for component in (usb, can, rs485):
        assert all(item.calculation_id and item.evidence_ids for item in [*component.bypass_caps, *component.straps])
