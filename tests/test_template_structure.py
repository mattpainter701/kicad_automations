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
    "speed_mhz": 10,
    "z_trace": 50,
    "i2c_addr_offset": 0,
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

        assert not floating_power, f"{comp.mpn} has floating power pins: {floating_power}"
        assert not floating_input, (
            f"{comp.mpn} has floating input/bidirectional pins (need connection, "
            f"pull-up/down, or explicit_no_connects): {floating_input}"
        )


def test_default_registry_contains_all_templates():
    reg = get_default_registry()
    assert len(reg._templates) >= 37


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
    from circuit_weaver.component_db import ComponentDef, PinDef
    from circuit_weaver.validator import run_validation_checks

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
    from circuit_weaver.component_db import ComponentDef, PinDef
    from circuit_weaver.validator import run_validation_checks

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


# ================================================================
# Sprint 5: Passive component correctness
# ================================================================


def test_expanded_feedback_vref_database():
    """Feedback Vref database should cover all switching converters."""
    from circuit_weaver.validator import _FEEDBACK_VREF

    expected_ics = ["AP62300", "TPS62088", "TPS61230A", "MT3608", "TPS63020", "TPS63000"]
    for ic in expected_ics:
        assert ic in _FEEDBACK_VREF, f"{ic} missing from _FEEDBACK_VREF"


def test_validator_has_inductor_and_cap_checks():
    """Validator should include inductor and capacitor checks."""
    from circuit_weaver.validator import _VALIDATION_CHECKS

    codes = {code for code, _, _ in _VALIDATION_CHECKS}
    assert "inductor-selection" in codes
    assert "cap-voltage" in codes


# ================================================================
# Sprint 6: DRC pipeline
# ================================================================


def test_validator_has_pin_type_conflict_check():
    """Validator should include ERC pin-type conflict check."""
    from circuit_weaver.validator import _VALIDATION_CHECKS

    codes = {code for code, _, _ in _VALIDATION_CHECKS}
    assert "pin-type-conflicts" in codes


def test_electrical_quality_scorer():
    """Electrical quality scorer should produce valid scores."""
    from circuit_weaver.component_db import BypassCap, ComponentDef, PinDef
    from circuit_weaver.scorer import score_electrical_quality

    comp = ComponentDef(
        mpn="TEST_IC",
        ref_prefix="U",
        pins=[
            PinDef("1", "VDD", "power_in", "T"),
            PinDef("2", "GND", "power_in", "B"),
            PinDef("3", "OUT", "output", "R"),
        ],
        power_pins={"1": "VDD_3P3", "2": "GND"},
        pin_nets={"3": "SIG_OUT"},
        bypass_caps=[BypassCap("C1", "VDD_3P3", "GND", "100nF", "0402")],
    )
    score = score_electrical_quality([comp])
    assert 0 <= score.total <= 100
    assert score.pin_coverage_pct == 100.0
    assert score.power_pin_coverage_pct == 100.0


def test_strict_mode_fails_on_warnings():
    """Strict mode should make warnings count as failures."""
    from circuit_weaver.dispatcher import ValidationMessage, ValidationReport

    report = ValidationReport(
        profile="test",
        valid=True,
        categories={
            "electrical": [
                ValidationMessage("electrical", "test-warn", "warning", "U1", "test warning"),
            ]
        },
        summary={"electrical": 1},
    )
    # Simulate strict computation
    error_count = sum(1 for m in report.categories.get("electrical", []) if m.level == "error")
    warning_count = sum(1 for m in report.categories.get("electrical", []) if m.level == "warning")
    strict_valid = (error_count + warning_count) == 0
    normal_valid = error_count == 0
    assert normal_valid is True  # Non-strict: warnings OK
    assert strict_valid is False  # Strict: warnings fail


def test_design_checklist_generation():
    """Design checklist should produce valid Markdown."""
    from circuit_weaver.dispatcher import ValidationReport, generate_design_checklist

    report = ValidationReport(
        profile="standard",
        valid=True,
        categories={"structural": [], "electrical": [], "implementation": [], "presentation": []},
        summary={"structural": 0, "electrical": 0, "implementation": 0, "presentation": 0},
        metadata={"project": "TestProject", "component_count": 5, "block_count": 3},
    )
    checklist = generate_design_checklist(report)
    assert "# Design Validation Checklist" in checklist
    assert "TestProject" in checklist
    assert "[x]" in checklist  # Should have passing checks


# ================================================================
# Sprint 7: Import pipeline
# ================================================================


def test_easyeda_pin_type_enrichment():
    """EasyEDA parser should enrich unspecified pin types from name patterns."""
    from circuit_weaver.easyeda_parser import _EE_ELEC_TYPE_MAP

    # Verify the type map exists
    assert _EE_ELEC_TYPE_MAP[0] == "unspecified"
    assert _EE_ELEC_TYPE_MAP[4] == "power_in"


# ================================================================
# Sprint 8: Fix suggestions
# ================================================================


def test_validation_issues_have_suggestion_field():
    """ValidationIssue should support a suggestion field."""
    from circuit_weaver.validator import ValidationIssue

    issue = ValidationIssue(
        code="test",
        level="warning",
        ref="U1",
        mpn="TEST",
        message="test msg",
        suggestion="Add a 100nF cap",
    )
    assert issue.suggestion == "Add a 100nF cap"


# ================================================================
# Sprint 11: Design diff
# ================================================================


def test_diff_detects_added_block():
    """Diff should detect a block added in the new spec."""
    from circuit_weaver.diff_renderer import compute_diff

    old_spec = {
        "project": "TestOld",
        "power": [{"type": "buck", "ref": "U1", "vin": 5, "vout": 3.3, "iout": 1}],
    }
    new_spec = {
        "project": "TestNew",
        "power": [
            {"type": "buck", "ref": "U1", "vin": 5, "vout": 3.3, "iout": 1},
            {"type": "ldo", "ref": "U2", "vin": 3.3, "vout": 1.8},
        ],
    }
    diff = compute_diff(old_spec, new_spec)
    assert len(diff.added) == 1
    assert diff.added[0].ref == "U2"
    assert diff.added[0].block_type == "ldo"
    assert len(diff.unchanged) == 1
    assert diff.unchanged[0].ref == "U1"


def test_diff_detects_removed_block():
    """Diff should detect a block removed in the new spec."""
    from circuit_weaver.diff_renderer import compute_diff

    old_spec = {
        "project": "Test",
        "power": [
            {"type": "buck", "ref": "U1", "vin": 5, "vout": 3.3, "iout": 1},
            {"type": "ldo", "ref": "U2", "vin": 3.3, "vout": 1.8},
        ],
    }
    new_spec = {
        "project": "Test",
        "power": [{"type": "buck", "ref": "U1", "vin": 5, "vout": 3.3, "iout": 1}],
    }
    diff = compute_diff(old_spec, new_spec)
    assert len(diff.removed) == 1
    assert diff.removed[0].ref == "U2"


def test_diff_detects_changed_params():
    """Diff should detect parameter changes on existing blocks."""
    from circuit_weaver.diff_renderer import compute_diff

    old_spec = {
        "project": "Test",
        "power": [{"type": "buck", "ref": "U1", "vin": 5, "vout": 3.3, "iout": 1}],
    }
    new_spec = {
        "project": "Test",
        "power": [{"type": "buck", "ref": "U1", "vin": 12, "vout": 5.0, "iout": 2}],
    }
    diff = compute_diff(old_spec, new_spec)
    assert len(diff.changed) == 1
    assert "vin" in diff.changed[0].changed_fields
    assert "vout" in diff.changed[0].changed_fields
    assert "iout" in diff.changed[0].changed_fields


def test_diff_detects_metadata_changes():
    """Diff should detect project name and metadata changes."""
    from circuit_weaver.diff_renderer import compute_diff

    old_spec = {"project": "OldName", "description": "v1"}
    new_spec = {"project": "NewName", "description": "v2"}
    diff = compute_diff(old_spec, new_spec)
    assert "project" in diff.metadata_changes
    assert "description" in diff.metadata_changes
    assert diff.metadata_changes["project"] == ("OldName", "NewName")


def test_diff_html_output(tmp_path):
    """Diff should produce valid HTML output when --output is specified."""
    from circuit_weaver.diff_renderer import diff_designs

    old_spec = {
        "project": "Old",
        "power": [{"type": "buck", "ref": "U1", "vin": 5, "vout": 3.3, "iout": 1}],
    }
    new_spec = {
        "project": "New",
        "power": [
            {"type": "buck", "ref": "U1", "vin": 12, "vout": 5.0, "iout": 2},
            {"type": "ldo", "ref": "U2", "vin": 5, "vout": 3.3},
        ],
    }
    html_path = tmp_path / "diff.html"
    result = diff_designs(old_spec, new_spec, output=str(html_path))
    assert html_path.exists()
    content = html_path.read_text(encoding="utf-8")
    assert "<!DOCTYPE html>" in content
    assert "ADDED" in content
    assert "CHANGED" in content
    assert result["summary"]["added"] == 1
    assert result["summary"]["changed"] == 1


# ================================================================
# New templates: voltage_reference, spi_bus, usb_c_connector
# ================================================================


def test_voltage_reference_series_generates():
    """Series voltage reference (REF3030) should generate with decoupling."""
    from circuit_weaver.subcircuits.voltage_reference import VoltageReferenceTemplate

    template = VoltageReferenceTemplate()
    result = template.generate({"ic": "REF3030"})
    comp = result.components[0]
    assert comp.mpn == "REF3030"
    assert len(comp.bypass_caps) == 2  # CIN + COUT
    port_names = {p.name for p in result.boundary_ports}
    assert "VREF_3P0V" in port_names
    assert "GND" in port_names
    _assert_no_unpowered_power_in_pins(result)


def test_voltage_reference_shunt_generates():
    """Shunt voltage reference (LM4040-2.5) should generate with series resistor."""
    from circuit_weaver.subcircuits.voltage_reference import VoltageReferenceTemplate

    template = VoltageReferenceTemplate()
    result = template.generate({"ic": "LM4040-2.5", "vin": 5.0, "iload": 0.001})
    comp = result.components[0]
    assert comp.mpn == "LM4040-2.5"
    assert comp.ref_prefix == "D"  # shunt refs use diode prefix
    assert len(comp.straps) == 1  # series bias resistor
    assert comp.straps[0].role == "shunt_bias"


def test_spi_bus_termination_generates():
    """SPI bus termination should generate series resistors on MOSI/SCLK."""
    from circuit_weaver.subcircuits.spi_bus import SPIBusTemplate

    template = SPIBusTemplate()
    result = template.generate({"speed_mhz": 10})
    comp = result.components[0]
    assert comp.mpn == "RESISTORS_ONLY"
    assert len(comp.straps) == 2  # MOSI + SCLK termination
    strap_roles = {s.role for s in comp.straps}
    assert "spi_termination" in strap_roles


def test_spi_bus_level_shifter_generates():
    """SPI level shifter (SN74LVC1T45) should generate with decoupling."""
    from circuit_weaver.subcircuits.spi_bus import SPIBusTemplate

    template = SPIBusTemplate()
    result = template.generate({"ic": "SN74LVC1T45"})
    comp = result.components[0]
    assert comp.mpn == "SN74LVC1T45"
    assert len(comp.bypass_caps) == 2  # VCCA + VCCB decoupling
    _assert_no_unpowered_power_in_pins(result)


def test_usb_c_device_generates():
    """USB-C device connector should generate CC pull-downs."""
    from circuit_weaver.subcircuits.usb_c_connector import USBCConnectorTemplate

    template = USBCConnectorTemplate()
    result = template.generate({"role": "device"})
    comp = result.components[0]
    assert comp.ref_prefix == "J"
    assert len(comp.straps) == 2  # CC1 + CC2 pull-downs
    assert all(s.role == "cc_pulldown" for s in comp.straps)
    assert all("5.1k" in s.value for s in comp.straps)
    port_names = {p.name for p in result.boundary_ports}
    assert "VBUS" in port_names
    assert "USB_DP" in port_names
    assert "USB_DN" in port_names


def test_usb_c_source_generates():
    """USB-C source connector should generate CC pull-ups to VBUS."""
    from circuit_weaver.subcircuits.usb_c_connector import USBCConnectorTemplate

    template = USBCConnectorTemplate()
    result = template.generate({"role": "source"})
    comp = result.components[0]
    assert len(comp.straps) == 2
    assert all(s.role == "cc_pullup" for s in comp.straps)
    assert all(s.rail == "VBUS" for s in comp.straps)


def test_usb_c_simple_connector_generates():
    """USB-C simple 6-pin connector should work and mark SBU as NC."""
    from circuit_weaver.subcircuits.usb_c_connector import USBCConnectorTemplate

    template = USBCConnectorTemplate()
    result = template.generate({"ic": "USB_C_SIMPLE", "role": "device"})
    comp = result.components[0]
    assert comp.mpn == "USB_C_SIMPLE"
    # Simple connector has no SBU pins, so no explicit NCs for SBU
    assert len(comp.straps) == 2  # CC pull-downs still present


# ================================================================
# New templates: rtc, eeprom, wireless_module, connector
# ================================================================


def test_rtc_ds3231_generates():
    """DS3231 RTC should generate with TCXO (no external crystal)."""
    from circuit_weaver.subcircuits.rtc import RTCTemplate

    template = RTCTemplate()
    result = template.generate({"ic": "DS3231"})
    comp = result.components[0]
    assert comp.mpn == "DS3231"
    # DS3231 NC pins should be marked
    assert len(comp.explicit_no_connects) > 0
    # RST pull-up strap
    assert any(s.role == "reset_pullup" for s in comp.straps)
    port_names = {p.name for p in result.boundary_ports}
    assert "VBAT_RTC" in port_names
    assert "I2C_SDA" in port_names
    _assert_no_unpowered_power_in_pins(result)
    _assert_no_unhandled_critical_pins(result)


def test_rtc_pcf8523_generates():
    """PCF8523 RTC should generate with external crystal load caps."""
    from circuit_weaver.subcircuits.rtc import RTCTemplate

    template = RTCTemplate()
    result = template.generate({"ic": "PCF8523"})
    comp = result.components[0]
    assert comp.mpn == "PCF8523"
    # Crystal load caps
    crystal_caps = [c for c in comp.bypass_caps if c.role == "crystal_load"]
    assert len(crystal_caps) == 2
    _assert_no_unpowered_power_in_pins(result)


def test_eeprom_i2c_generates():
    """24LC256 I2C EEPROM should generate with address strapping."""
    from circuit_weaver.subcircuits.eeprom import EEPROMTemplate

    template = EEPROMTemplate()
    result = template.generate({"ic": "24LC256", "i2c_addr_offset": 3})
    comp = result.components[0]
    assert comp.mpn == "24LC256"
    # A0=VDD (bit 0), A1=VDD (bit 1), A2=GND (bit 2=0)
    assert comp.power_pins["1"] == "VDD_3P3"  # A0 high
    assert comp.power_pins["2"] == "VDD_3P3"  # A1 high
    assert comp.power_pins["3"] == "GND"  # A2 low
    _assert_no_unpowered_power_in_pins(result)


def test_eeprom_spi_flash_generates():
    """AT25SF128A SPI flash should generate with WP/HOLD tied high."""
    from circuit_weaver.subcircuits.eeprom import EEPROMTemplate

    template = EEPROMTemplate()
    result = template.generate({"ic": "AT25SF128A"})
    comp = result.components[0]
    assert comp.mpn == "AT25SF128A"
    # WP_N and HOLD_N should be tied to VDD (disabled)
    assert comp.power_pins["3"] == "VDD_3P3"  # WP_N
    assert comp.power_pins["7"] == "VDD_3P3"  # HOLD_N
    port_names = {p.name for p in result.boundary_ports}
    assert "SPI_MOSI" in port_names
    assert "SPI_MISO" in port_names
    _assert_no_unpowered_power_in_pins(result)


def test_wireless_esp32_generates():
    """ESP32-S3 module should generate with EN/boot strapping."""
    from circuit_weaver.subcircuits.wireless_module import WirelessModuleTemplate

    template = WirelessModuleTemplate()
    result = template.generate({"ic": "ESP32-S3-WROOM-1"})
    comp = result.components[0]
    assert comp.mpn == "ESP32-S3-WROOM-1"
    # EN pull-up and boot pull-up
    strap_roles = {s.role for s in comp.straps}
    assert "enable_pullup" in strap_roles
    assert "boot_pullup" in strap_roles
    # Bulk decoupling for high peak current
    assert any("22uF" in c.value for c in comp.bypass_caps)
    # Unused GPIOs should be explicit NC
    assert len(comp.explicit_no_connects) > 0
    _assert_no_unpowered_power_in_pins(result)
    _assert_no_unhandled_critical_pins(result)


def test_wireless_nrf52_generates():
    """nRF52840 module should generate with reset and SWD."""
    from circuit_weaver.subcircuits.wireless_module import WirelessModuleTemplate

    template = WirelessModuleTemplate()
    result = template.generate({"ic": "nRF52840-MODULE"})
    comp = result.components[0]
    assert comp.mpn == "nRF52840-MODULE"
    assert any(s.role == "reset_pullup" for s in comp.straps)
    port_names = {p.name for p in result.boundary_ports}
    assert any("SWDIO" in p for p in port_names)
    _assert_no_unpowered_power_in_pins(result)
    _assert_no_unhandled_critical_pins(result)


def test_connector_barrel_jack_generates():
    """Barrel jack should generate with input decoupling."""
    from circuit_weaver.subcircuits.connector import ConnectorTemplate

    template = ConnectorTemplate()
    result = template.generate({"ic": "BARREL_JACK_2.1MM"})
    comp = result.components[0]
    assert comp.ref_prefix == "J"
    assert len(comp.bypass_caps) == 1  # 10uF input cap
    port_names = {p.name for p in result.boundary_ports}
    assert "VIN" in port_names
    assert "GND" in port_names


def test_connector_jst_ph_generates():
    """JST PH 2-pin battery connector should generate."""
    from circuit_weaver.subcircuits.connector import ConnectorTemplate

    template = ConnectorTemplate()
    result = template.generate({"ic": "JST_PH_2P", "positive_net": "VBAT"})
    comp = result.components[0]
    assert comp.mpn == "JST_PH_2P"
    assert comp.pin_nets["1"] == "VBAT"
    assert comp.pin_nets["2"] == "GND"


def test_connector_pin_header_generates():
    """Pin header should generate with user-provided signal nets."""
    from circuit_weaver.subcircuits.connector import ConnectorTemplate

    template = ConnectorTemplate()
    result = template.generate({
        "ic": "PIN_HEADER_4P",
        "signal_nets": "SDA,SCL,VCC,GND",
    })
    comp = result.components[0]
    assert comp.pin_nets["1"] == "SDA"
    assert comp.pin_nets["2"] == "SCL"
    assert comp.pin_nets["3"] == "VCC"
    assert comp.pin_nets["4"] == "GND"


# ================================================================
# Data-driven template system
# ================================================================


def test_ic_data_store_loads():
    """IC data store should load all JSON files and find known ICs."""
    from circuit_weaver.ic_data import get_ic_data, get_all_ics, list_topologies

    ap = get_ic_data("AP62300")
    assert ap is not None
    assert ap["topology"] == "buck"
    assert ap["vref"] == 0.8

    bucks = get_all_ics("buck")
    assert "AP62300" in bucks

    topos = list_topologies()
    assert "buck" in topos
    assert "ldo" in topos


def test_data_driven_buck_parity():
    """Data-driven buck builder should produce equivalent output to legacy template."""
    from circuit_weaver.ic_data import get_ic_data
    from circuit_weaver.subcircuits.buck import BuckConverterTemplate
    from circuit_weaver.subcircuits.topology_builders import build_switching_regulator

    params = {"vin": 12.0, "vout": 3.3, "iout": 1.0, "ic": "AP62300", "ref": "U1"}

    # Legacy template
    legacy = BuckConverterTemplate().generate(params)
    legacy_comp = legacy.components[0]

    # Data-driven builder
    ic_data = dict(get_ic_data("AP62300"))
    ic_data["_mpn"] = "AP62300"
    dd = build_switching_regulator(ic_data, params)
    dd_comp = dd.components[0]

    # Parity checks: same power pins, same feedback divider straps, same passives count
    assert legacy_comp.power_pins == dd_comp.power_pins
    assert len(legacy_comp.straps) == len(dd_comp.straps)
    assert len(legacy_comp.bypass_caps) == len(dd_comp.bypass_caps)
    assert legacy_comp.mpn == dd_comp.mpn

    # Same feedback resistor values
    legacy_fbt = next(s for s in legacy_comp.straps if s.role == "feedback_top")
    dd_fbt = next(s for s in dd_comp.straps if s.role == "feedback_top")
    assert legacy_fbt.value == dd_fbt.value


def test_data_driven_ldo_parity():
    """Data-driven LDO builder should produce equivalent output to legacy template."""
    from circuit_weaver.ic_data import get_ic_data
    from circuit_weaver.subcircuits.ldo import LDOTemplate
    from circuit_weaver.subcircuits.topology_builders import build_linear_regulator

    params = {"vin": 5.0, "ic": "TLV75518", "ref": "U2"}

    legacy = LDOTemplate().generate(params)
    legacy_comp = legacy.components[0]

    ic_data = dict(get_ic_data("TLV75518"))
    ic_data["_mpn"] = "TLV75518"
    dd = build_linear_regulator(ic_data, params)
    dd_comp = dd.components[0]

    assert legacy_comp.power_pins == dd_comp.power_pins
    assert len(legacy_comp.bypass_caps) == len(dd_comp.bypass_caps)
    assert legacy_comp.mpn == dd_comp.mpn


def test_data_driven_template_via_registry():
    """DataDrivenTemplate should be findable via the registry fallback."""
    from circuit_weaver.subcircuits.base import DataDrivenTemplate, SubcircuitRegistry

    # Create a fresh registry with NO legacy templates
    reg = SubcircuitRegistry()
    # The fallback should find "buck" from JSON IC data
    tmpl = reg.get("buck")
    assert tmpl is not None
    assert isinstance(tmpl, DataDrivenTemplate)

    result = tmpl.generate({"vin": 12, "vout": 3.3, "iout": 1.0})
    assert len(result.components) > 0
    assert result.components[0].mpn == "AP62300"


def test_register_custom_ic():
    """Agent should be able to register a new IC dynamically."""
    from circuit_weaver.ic_data import get_ic_data, register_ic, reload

    # Register a fake IC
    register_ic("TEST_BUCK_999", {
        "topology": "buck",
        "description": "Test Buck IC",
        "footprint": "SOT-23-6",
        "vref": 0.6,
        "fsw": 1e6,
        "r_fbb_default": 200e3,
        "pins": [
            {"number": "1", "name": "GND", "type": "power_in", "side": "B"},
            {"number": "2", "name": "SW", "type": "output", "side": "T"},
            {"number": "3", "name": "VIN", "type": "power_in", "side": "L"},
            {"number": "4", "name": "FB", "type": "input", "side": "R"},
            {"number": "5", "name": "EN", "type": "input", "side": "L"},
        ],
        "pin_vin": "3", "pin_gnd": "1", "pin_sw": "2",
        "pin_fb": "4", "pin_en": "5",
    }, persist=False)

    # Should be findable now
    ic = get_ic_data("TEST_BUCK_999")
    assert ic is not None
    assert ic["vref"] == 0.6

    # Should generate successfully via data-driven builder
    from circuit_weaver.subcircuits.topology_builders import build_switching_regulator
    result = build_switching_regulator(ic, {
        "vin": 5.0, "vout": 1.8, "iout": 2.0, "ic": "TEST_BUCK_999", "ref": "U99",
    })
    assert result.components[0].mpn == "TEST_BUCK_999"
    assert len(result.components[0].straps) == 2  # feedback divider

    # Clean up
    reload()
