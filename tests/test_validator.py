"""Tests for validator.py — pinout source validation (Task 116) and related checks."""

from __future__ import annotations

from circuit_weaver.component_db import ComponentDef, ComponentRegistry, PinDef
from circuit_weaver.project_spec import resolve_project_spec
from circuit_weaver.validator import run_validation_checks, validate_circuit

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _stub_ic(ref: str = "U1", mpn: str = "BGB707E6327XTSA1") -> ComponentDef:
    """ComponentDef that simulates a DigiKey/Mouser stub (pinout_source='stub')."""
    return ComponentDef(
        mpn=mpn,
        ref_prefix="U",
        source_ref=ref,
        value=mpn,
        description="RF Transistor",
        pinout_source="stub",
        pins=[PinDef("1", "~", "passive", "L"), PinDef("2", "~", "passive", "R")],
    )


def _explicit_ic(ref: str = "U2", mpn: str = "ESP32-WROOM-32E") -> ComponentDef:
    """ComponentDef with a fully specified pin map (pinout_source='explicit')."""
    return ComponentDef(
        mpn=mpn,
        ref_prefix="U",
        source_ref=ref,
        value=mpn,
        description="WiFi/BT Module",
        pinout_source="explicit",
        pins=[
            PinDef("1", "GND", "power_in", "L"),
            PinDef("2", "VCC", "power_in", "L"),
            PinDef("3", "EN", "input", "R"),
        ],
        pin_nets={"3": "nRST"},
        power_pins={"1": "GND", "2": "3V3"},
    )


def _verified_stub(ref: str = "U3", mpn: str = "UNKNOWN_IC") -> ComponentDef:
    """Stub whose user has acknowledged the pinout via pinout_verified=True."""
    return ComponentDef(
        mpn=mpn,
        ref_prefix="U",
        source_ref=ref,
        value=mpn,
        description="Custom IC",
        pinout_source="stub",
        pinout_verified=True,
        pins=[PinDef("1", "~", "passive", "L"), PinDef("2", "~", "passive", "R")],
    )


def _passive_resistor(ref: str = "R1") -> ComponentDef:
    return ComponentDef(
        mpn="RC0402FR-0710KL",
        ref_prefix="R",
        source_ref=ref,
        value="10k",
        pinout_source="stub",  # stub on a passive — should NOT raise error
    )


def _stub_diode(ref: str = "D1") -> ComponentDef:
    return ComponentDef(
        mpn="SMBJ5.0A",
        ref_prefix="D",
        source_ref=ref,
        value="SMBJ5.0A",
        description="TVS diode",
        pinout_source="stub",
        pins=[PinDef("1", "~", "passive", "L"), PinDef("2", "~", "passive", "R")],
    )


def _stub_registry_component(mpn: str = "UNKNOWN_IC", ref_prefix: str = "U") -> ComponentRegistry:
    registry = ComponentRegistry()
    registry.register(
        ComponentDef(
            mpn=mpn,
            ref_prefix=ref_prefix,
            value=mpn,
            description="Distributor-derived stub",
            pinout_source="stub",
            pins=[PinDef("1", "~", "passive", "L"), PinDef("2", "~", "passive", "R")],
        )
    )
    return registry


# ---------------------------------------------------------------------------
# Task 116 — pinout-source validation
# ---------------------------------------------------------------------------


def test_stub_ic_is_a_verified_blocker():
    """A known stub pinout remains a confirmed generation safety defect."""
    issues = validate_circuit([_stub_ic()])
    pinout_issues = [i for i in issues if i.code == "unverified-pinout"]
    assert pinout_issues, "Expected unverified-pinout review item for stub IC"
    assert pinout_issues[0].severity == "blocker"
    assert pinout_issues[0].detection_confidence == "verified"
    assert pinout_issues[0].level == "error"
    assert pinout_issues[0].is_confirmed_blocker
    assert "BGB707" in pinout_issues[0].message


def test_explicit_ic_passes_validation():
    """An IC with explicit pinout must NOT produce an unverified-pinout error."""
    issues = validate_circuit([_explicit_ic()])
    pinout_errors = [i for i in issues if i.code == "unverified-pinout"]
    assert not pinout_errors, f"Unexpected pinout error for explicit IC: {pinout_errors}"


def test_pinout_verified_flag_suppresses_error():
    """pinout_verified=True must suppress the unverified-pinout error even for stubs."""
    issues = validate_circuit([_verified_stub()])
    pinout_errors = [i for i in issues if i.code == "unverified-pinout"]
    assert not pinout_errors, "pinout_verified=True should suppress unverified-pinout error"


def test_passive_stub_not_flagged():
    """Passives (ref_prefix R/C/L/D…) must never generate unverified-pinout errors."""
    issues = validate_circuit([_passive_resistor()])
    pinout_errors = [i for i in issues if i.code == "unverified-pinout"]
    assert not pinout_errors, "Passives should never trigger unverified-pinout"


def test_diode_stub_is_flagged():
    """Polarized two-pin parts like diodes still need verified pin assignments."""
    issues = validate_circuit([_stub_diode()])
    pinout_errors = [i for i in issues if i.code == "unverified-pinout"]
    assert pinout_errors, "Diode stubs should not bypass pinout verification"


def test_mixed_design_only_stubs_fail():
    """In a mixed design only unverified stub ICs emit errors; others are clean."""
    components = [_stub_ic("U1"), _explicit_ic("U2"), _verified_stub("U3"), _passive_resistor("R1")]
    issues = validate_circuit(components)
    pinout_errors = [i for i in issues if i.code == "unverified-pinout"]
    assert len(pinout_errors) == 1
    assert pinout_errors[0].ref == "U1"


def test_multiple_stubs_each_emit_error():
    """Each unverified stub IC in the design must produce its own error entry."""
    components = [_stub_ic("U1", "PART_A"), _stub_ic("U2", "PART_B")]
    issues = validate_circuit(components)
    pinout_errors = [i for i in issues if i.code == "unverified-pinout"]
    assert len(pinout_errors) == 2
    refs = {i.ref for i in pinout_errors}
    assert refs == {"U1", "U2"}


def test_run_validation_checks_includes_pinout_check():
    """A verified observation of stub pinout state remains a hard-fail result."""
    results = run_validation_checks([_stub_ic()])
    pinout_result = next((r for r in results if r.code == "pinout-source"), None)
    assert pinout_result is not None, "pinout-source check not registered in _VALIDATION_CHECKS"
    assert pinout_result.status == "FAIL"
    assert any(i.code == "unverified-pinout" for i in pinout_result.issues)


def test_pinout_verified_flag_from_spec_suppresses_error():
    """Spec-level pinout_verified must flow through project resolution."""
    spec = {
        "project": "pinout_override",
        "digital": [{"ic": "UNKNOWN_IC", "ref": "U1", "pinout_verified": True}],
    }
    components, _metadata = resolve_project_spec(spec, component_reg=_stub_registry_component())
    assert components[0].pinout_verified is True
    pinout_errors = [i for i in validate_circuit(components) if i.code == "unverified-pinout"]
    assert not pinout_errors


def test_explicit_pin_map_from_spec_marks_component_trusted():
    """Spec-level pin_map must replace stub placeholder pins and clear the gate."""
    spec = {
        "project": "pin_map_override",
        "digital": [
            {
                "ic": "UNKNOWN_IC",
                "ref": "U1",
                "pin_map": {"1": "RF_IN", "2": "GND", "3": "VDD_3P3"},
            }
        ],
    }
    components, _metadata = resolve_project_spec(spec, component_reg=_stub_registry_component())
    comp = components[0]
    assert comp.pinout_source == "explicit"
    assert {pin.number for pin in comp.pins} == {"1", "2", "3"}
    assert comp.pin_nets == {"1": "RF_IN"}
    assert comp.power_pins == {"2": "GND", "3": "VDD_3P3"}
    pinout_errors = [i for i in validate_circuit([comp]) if i.code == "unverified-pinout"]
    assert not pinout_errors
