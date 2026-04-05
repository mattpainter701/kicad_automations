"""Structural regression tests for the subcircuit template registry."""

from __future__ import annotations

import re

from circuit_weaver.subcircuits.base import get_default_registry
from circuit_weaver.subcircuits.buck import BUCK_IC_DATABASE, BuckConverterTemplate
from circuit_weaver.subcircuits.clock import ClockSynthTemplate
from circuit_weaver.subcircuits.driver import GateDriverTemplate, LevelShifterTemplate
from circuit_weaver.subcircuits.mosfet_switch import MOSFETSwitchTemplate
from circuit_weaver.subcircuits.power_mux import POWER_MUX_IC_DATABASE
from circuit_weaver.subcircuits.usb import USBControllerTemplate

_NC_PIN_NAME_RE = re.compile(r"^(~|NC|DNC|N\.?C\.?|NO.?CONNECT|RESERVED)$", re.IGNORECASE)

SAMPLE_VALUES = {
    "protect_net": "SIG_IN",
    "vin": 12.0,
    "vout": 3.3,
    "iout": 1.0,
    "ilim": 1.0,
    "iload": 0.5,
    "vcoil": 12.0,
    "icoil": 0.05,
    "vdrive": 3.3,
    "ref_freq": 30.72e6,
    "pll_bw": 20e3,
    "ports": 4,
    "channels_used": 1,
    "bus_voltage": 24.0,
    "standoff_voltage": 26.0,
}


def _build_params(template) -> dict[str, object]:
    params: dict[str, object] = {}
    for spec in template.param_schema:
        key = spec["name"]
        if "options" in spec:
            params[key] = spec["options"][0]
        elif "enum" in spec:
            params[key] = spec["enum"][0]
        elif key in SAMPLE_VALUES:
            params[key] = SAMPLE_VALUES[key]
        elif spec.get("type") == "boolean":
            params[key] = spec.get("default", False)
        elif spec.get("type") == "integer":
            params[key] = spec.get("default", max(spec.get("minimum", 1), 1))
        elif spec.get("type") == "number":
            params[key] = spec.get("default", max(spec.get("minimum", 0.1), 0.1))
        elif "default" in spec:
            params[key] = spec["default"]
        elif spec.get("required"):
            params[key] = f"{key.upper()}_TEST"
    return params


def _assert_no_unpowered_power_in_pins(result) -> None:
    for comp in result.components:
        floating = [
            f"{comp.ref_prefix}:{pin.number}:{pin.name}"
            for pin in comp.pins
            if pin.electrical_type == "power_in"
            and pin.number not in comp.power_pins
            and pin.number not in comp.pin_nets
        ]
        assert not floating, f"{comp.mpn} leaves power pins unconnected: {floating}"


def _assert_no_unhandled_critical_pins(result) -> None:
    """Assert that no power_in or input pins are silently left floating.

    Every pin must be in pin_nets, power_pins, straps, explicit_no_connects,
    or have an NC-like name.  power_in pins trigger hard failures; input pins
    trigger soft failures with an explanatory message.
    """
    for comp in result.components:
        # Only check ICs
        if comp.ref_prefix.upper() not in ("U", "IC"):
            continue

        handled = set(comp.pin_nets) | set(comp.power_pins) | comp.explicit_no_connects
        for strap in comp.straps:
            handled.add(strap.pin)

        floating_power = []
        floating_input = []
        for pin in comp.pins:
            if pin.number in handled:
                continue
            if _NC_PIN_NAME_RE.match(pin.name):
                continue
            label = f"{comp.ref_prefix}:{pin.number}:{pin.name}({pin.electrical_type})"
            if pin.electrical_type == "power_in":
                floating_power.append(label)
            elif pin.electrical_type in ("input", "bidirectional", "tri_state"):
                floating_input.append(label)

        assert not floating_power, (
            f"{comp.mpn} has floating power pins: {floating_power}"
        )
        assert not floating_input, (
            f"{comp.mpn} has floating input/bidirectional pins (need connection, "
            f"pull-up/down, or explicit_no_connects): {floating_input}"
        )


def test_default_registry_contains_all_templates():
    reg = get_default_registry()
    assert len(reg._templates) >= 30


def test_all_default_templates_generate_and_power_pins_are_connected():
    reg = get_default_registry()
    for template_name in sorted(reg.available_types()):
        template = reg.get(template_name)
        result = template.generate(_build_params(template))
        assert result.components, f"{template_name} should generate at least one component"
        _assert_no_unpowered_power_in_pins(result)


def test_all_default_templates_have_no_unhandled_critical_pins():
    """Every power_in and input pin must be handled or explicitly marked NC."""
    reg = get_default_registry()
    for template_name in sorted(reg.available_types()):
        template = reg.get(template_name)
        result = template.generate(_build_params(template))
        _assert_no_unhandled_critical_pins(result)


def test_tps62088_grounds_its_exposed_pad():
    template = BuckConverterTemplate()
    result = template.generate({"vin": 12.0, "vout": 3.3, "iout": 1.0, "ic": "TPS62088"})
    comp = result.components[0]
    assert BUCK_IC_DATABASE["TPS62088"]["pin_gnd"] in comp.power_pins
    assert comp.power_pins["8"] == "GND"
    _assert_no_unpowered_power_in_pins(result)


def test_ucc27524_connects_duplicate_supply_pins():
    template = GateDriverTemplate()
    result = template.generate({"ic": "UCC27524"})
    comp = result.components[0]
    assert comp.power_pins["3"] == "GND"
    assert comp.power_pins["4"] == "GND"
    assert comp.power_pins["7"] == "VDD_12V"
    assert comp.power_pins["8"] == "VDD_12V"
    _assert_no_unpowered_power_in_pins(result)


def test_level_shifter_oe_uses_shared_pullup_net():
    template = LevelShifterTemplate()
    result = template.generate({"ic": "TXS0102", "ref": "U1"})
    comp = result.components[0]
    assert comp.pin_nets["7"] == "OE_U1"
    assert any(strap.net == "OE_U1" and strap.rail == "VDD_1P8" for strap in comp.straps)


def test_ad9528_exports_differential_reference_ports():
    template = ClockSynthTemplate()
    result = template.generate({"ic": "AD9528"})
    port_names = {port.name for port in result.boundary_ports}
    assert "REF_CLK_P" in port_names
    assert "REF_CLK_N" in port_names
    assert "REF_CLK" not in port_names


def test_fx3_assigns_and_exports_all_power_rails():
    template = USBControllerTemplate()
    result = template.generate({"ic": "CYUSB3014"})
    comp = result.components[0]
    assert comp.power_pins["A1"] == "VDD"
    assert comp.power_pins["A2"] == "DVDDIO"
    assert comp.power_pins["B1"] == "AVDD"
    assert comp.power_pins["B11"] == "VBUS"
    port_names = {port.name for port in result.boundary_ports}
    assert {"VDD", "DVDDIO", "AVDD", "VBUS", "GND"}.issubset(port_names)
    _assert_no_unpowered_power_in_pins(result)


def test_fx3_pmode0_is_explicit_no_connect():
    """CYUSB3014 PMODE0 (H1) is intentionally floating for SPI slave boot."""
    template = USBControllerTemplate()
    result = template.generate({"ic": "CYUSB3014"})
    comp = result.components[0]
    assert "H1" in comp.explicit_no_connects, "PMODE0 (H1) should be in explicit_no_connects"
    _assert_no_unhandled_critical_pins(result)


def test_icl7660_nc_pins_are_explicit_no_connects():
    """ICL7660 pins 1 (NC), 6 (LV), 7 (OSC) are intentionally unconnected."""
    from circuit_weaver.subcircuits.charge_pump import ChargePumpTemplate

    template = ChargePumpTemplate()
    result = template.generate({"ic": "ICL7660"})
    comp = result.components[0]
    assert {"1", "6", "7"}.issubset(comp.explicit_no_connects), (
        f"ICL7660 explicit_no_connects should include pins 1, 6, 7 but got {comp.explicit_no_connects}"
    )
    _assert_no_unhandled_critical_pins(result)


def test_p_channel_switch_drops_unused_ground_boundary():
    template = MOSFETSwitchTemplate()
    result = template.generate({"ic": "AO3401A", "iload": 0.5})
    port_names = {port.name for port in result.boundary_ports}
    assert "VDD_3P3" in port_names
    assert "GND" not in port_names


def test_power_mux_only_advertises_supported_variant():
    assert list(POWER_MUX_IC_DATABASE) == ["TPS2113ADRBR", "LTC4357CMS8"]


# ================================================================
# Sprint 3: Connectivity & bus validation
# ================================================================


def test_validator_catches_enable_pins():
    """Validator should detect floating EN pins on regulators."""
    from circuit_weaver.validator import run_validation_checks
    from circuit_weaver.component_db import ComponentDef, PinDef

    # Simulate a regulator with floating EN pin
    comp = ComponentDef(
        mpn="TEST_LDO",
        ref_prefix="U",
        category="power",
        pins=[
            PinDef("1", "VIN", "power_in", "L"),
            PinDef("2", "GND", "power_in", "B"),
            PinDef("3", "EN", "input", "L"),
            PinDef("4", "OUT", "power_out", "R"),
        ],
        power_pins={"1": "VDD_3P3", "2": "GND"},
        pin_nets={"4": "VOUT"},
        # EN pin 3 is NOT in pin_nets or power_pins — floating!
    )
    results = run_validation_checks([comp])
    en_result = next((r for r in results if r.code == "enable-pins"), None)
    assert en_result is not None, "enable-pins check should exist"
    assert en_result.status == "WARN", f"Expected WARN for floating EN, got {en_result.status}"
    assert any("EN" in i.message for i in en_result.issues)


def test_validator_bus_completeness_detects_missing_pullup():
    """I2C bus without pull-ups should be flagged."""
    from circuit_weaver.validator import run_validation_checks
    from circuit_weaver.component_db import ComponentDef, PinDef

    comp = ComponentDef(
        mpn="TEST_I2C",
        ref_prefix="U",
        pins=[
            PinDef("1", "SCL", "input", "L"),
            PinDef("2", "SDA", "bidirectional", "L"),
            PinDef("3", "VCC", "power_in", "T"),
            PinDef("4", "GND", "power_in", "B"),
        ],
        power_pins={"3": "VDD_3P3", "4": "GND"},
        pin_nets={"1": "I2C_SCL", "2": "I2C_SDA"},
        # No straps — missing pull-ups
    )
    results = run_validation_checks([comp])
    bus_result = next((r for r in results if r.code == "bus-completeness"), None)
    assert bus_result is not None
    assert bus_result.status == "WARN"
    assert any("pull-up" in i.message for i in bus_result.issues)


# ================================================================
# Sprint 4: Template quality & contract validation
# ================================================================


def test_all_templates_pass_contract_validation():
    """Every template's generate() output must satisfy the component contract."""
    reg = get_default_registry()
    for template_name in sorted(reg.available_types()):
        template = reg.get(template_name)
        result = template.generate(_build_params(template))
        errors = result.validate_contract()
        assert not errors, f"{template_name} contract errors: {errors}"


def test_schema_validation_catches_invalid_type():
    """Schema validation should catch wrong parameter types."""
    template = BuckConverterTemplate()
    errors = template._validate_params_from_schema({"vin": "not_a_number", "vout": 3.3, "iout": 1.0})
    assert any("number" in e for e in errors), f"Expected type error, got: {errors}"


def test_schema_validation_catches_invalid_option():
    """Schema validation should catch invalid option values."""
    from circuit_weaver.subcircuits.opamp import OpAmpTemplate

    template = OpAmpTemplate()
    errors = template._validate_params_from_schema({"config": "invalid_config"})
    assert any("must be one of" in e for e in errors), f"Expected option error, got: {errors}"


def test_schema_validation_passes_for_valid_params():
    """Schema validation should pass for valid parameters."""
    template = BuckConverterTemplate()
    errors = template._validate_params_from_schema({"vin": 12.0, "vout": 3.3, "iout": 1.0})
    assert not errors, f"Unexpected errors: {errors}"
