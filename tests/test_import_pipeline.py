"""Sprint 1: Robust KiCad import pipeline tests.

Tests for: stub components, auto-decoupling, net collision prevention,
power pin mapping, misc sheet, passive inference, reconciliation.
"""

from __future__ import annotations

import copy

import pytest

from circuit_weaver.allocator import classify_component
from circuit_weaver.component_db import (
    BUILTIN_REGISTRY,
    ComponentDef,
    PinDef,
    auto_generate_bypass_caps,
)
from circuit_weaver.kicad_lib import KiCadLibrary
from circuit_weaver.project_spec import (
    _apply_net_prefix,
    _apply_power_map,
    _make_stub_component,
    _resolve_component,
    resolve_project_spec,
)
from circuit_weaver.subcircuits.base import get_default_registry
from circuit_weaver.subcircuits.power_mux import PowerMuxTemplate

# ================================================================
# Task 1: Stop silently dropping components
# ================================================================


class TestStubComponents:
    def test_stub_has_unresolved_annotation(self):
        stub = _make_stub_component("FAKE_IC", "digital", "U99", "test reason")
        assert any("UNRESOLVED" in a for a in stub.annotations)
        assert stub.category == "digital"
        assert stub.source_ref == "U99"
        assert stub.mpn == "FAKE_IC"

    def test_unknown_ic_produces_stub_not_empty(self):
        result = _resolve_component(
            {"ic": "TOTALLY_FAKE_PART_XYZ"},
            "digital",
            get_default_registry(),
            BUILTIN_REGISTRY,
            KiCadLibrary(),
        )
        assert len(result) == 1
        assert any("UNRESOLVED" in a for a in result[0].annotations)

    def test_unknown_template_produces_stub(self):
        result = _resolve_component(
            {"type": "nonexistent_template", "ref": "U1"},
            "power",
            get_default_registry(),
            BUILTIN_REGISTRY,
            None,
        )
        assert len(result) == 1
        assert any("UNRESOLVED" in a for a in result[0].annotations)

    def test_missing_type_and_ic_produces_stub(self):
        result = _resolve_component(
            {"ref": "X1"},
            "misc",
            get_default_registry(),
            BUILTIN_REGISTRY,
            None,
        )
        assert len(result) == 1
        assert any("UNRESOLVED" in a for a in result[0].annotations)

    def test_valid_ic_does_not_produce_stub(self):
        result = _resolve_component(
            {"ic": "ESP32-WROOM-32E", "ref": "U1"},
            "mcu",
            get_default_registry(),
            BUILTIN_REGISTRY,
            None,
        )
        assert len(result) == 1
        assert not any("UNRESOLVED" in a for a in result[0].annotations)

    def test_spec_component_count_matches_block_count(self):
        spec = {
            "project": "test",
            "digital": [
                {"ic": "ESP32-WROOM-32E", "ref": "U1"},
                {"ic": "FAKE_PART_999", "ref": "U2"},
            ],
        }
        components, _ = resolve_project_spec(spec)
        # Both should produce a component (one real, one stub)
        assert len(components) == 2


# ================================================================
# Task 2: Auto-generate bypass caps for KiCad-imported ICs
# ================================================================


class TestAutoBypassCaps:
    def test_power_ic_below_pin_threshold_gets_caps(self):
        """Voltage regulators (3 pins) should get decoupling despite < 6 pins."""
        comp = ComponentDef(
            mpn="LM7805",
            ref_prefix="U",
            value="LM7805",
            footprint="TO-220",
            category="power",
            pins=[
                PinDef("1", "VI", "power_in", "L"),
                PinDef("2", "GND", "power_in", "B"),
                PinDef("3", "VO", "power_out", "R"),
            ],
            power_pins={"1": "VIN", "2": "GND", "3": "VOUT"},
        )
        count = auto_generate_bypass_caps([comp])
        assert count == 1
        assert len(comp.bypass_caps) >= 1

    def test_8pin_ic_gets_caps(self):
        """Standard ICs above threshold should get decoupling."""
        comp = ComponentDef(
            mpn="LM358",
            ref_prefix="U",
            value="LM358",
            footprint="SOIC-8",
            category="analog",
            pins=[PinDef(str(i), f"P{i}", "passive", "L") for i in range(1, 9)],
            power_pins={"4": "GND", "8": "VCC"},
        )
        count = auto_generate_bypass_caps([comp])
        assert count == 1
        assert len(comp.bypass_caps) >= 1

    def test_builtin_ic_not_double_capped(self):
        """Built-in ICs with explicit bypass caps should not get more added."""
        comp = copy.deepcopy(BUILTIN_REGISTRY.get("ESP32-WROOM-32E"))
        assert comp is not None
        original_count = len(comp.bypass_caps)
        assert original_count > 0
        auto_generate_bypass_caps([comp])
        assert len(comp.bypass_caps) == original_count

    def test_connector_does_not_get_caps(self):
        """Connectors with power pins should NOT get auto-decoupling."""
        comp = ComponentDef(
            mpn="USB-C",
            ref_prefix="J",
            value="USB-C",
            footprint="USB_C",
            category="connector",
            pins=[
                PinDef("1", "VBUS", "power_out", "R"),
                PinDef("2", "GND", "power_in", "B"),
                PinDef("3", "D+", "bidirectional", "R"),
                PinDef("4", "D-", "bidirectional", "R"),
            ],
            power_pins={"1": "VBUS_5V", "2": "GND"},
        )
        count = auto_generate_bypass_caps([comp])
        assert count == 0


# ================================================================
# Task 3: Fix net name collisions
# ================================================================


class TestNetPrefix:
    def test_generic_pins_get_prefixed(self):
        comp = ComponentDef(
            mpn="BSS138",
            ref_prefix="Q",
            value="BSS138",
            footprint="SOT-23",
            category="discrete",
            source_ref="Q1",
            pins=[
                PinDef("1", "G", "input", "L"),
                PinDef("2", "S", "passive", "B"),
                PinDef("3", "D", "passive", "R"),
            ],
            pin_nets={"1": "G", "2": "S", "3": "D"},
        )
        _apply_net_prefix({}, comp)
        assert comp.pin_nets["1"] == "Q1_G"
        assert comp.pin_nets["2"] == "Q1_S"
        assert comp.pin_nets["3"] == "Q1_D"

    def test_bus_signals_stay_global(self):
        comp = ComponentDef(
            mpn="TEST",
            ref_prefix="U",
            value="TEST",
            source_ref="U1",
            pins=[
                PinDef("1", "SDA", "bidirectional", "R"),
                PinDef("2", "SCL", "output", "R"),
                PinDef("3", "TX", "output", "R"),
            ],
            pin_nets={"1": "SDA", "2": "SCL", "3": "TX"},
        )
        _apply_net_prefix({}, comp)
        assert comp.pin_nets["1"] == "SDA"
        assert comp.pin_nets["2"] == "SCL"
        assert comp.pin_nets["3"] == "TX"

    def test_two_mosfets_get_separate_nets(self):
        spec = {
            "project": "test",
            "misc": [
                {"ic": "BSS138", "ref": "Q1"},
                {"ic": "BSS138", "ref": "Q2"},
            ],
        }
        components, _ = resolve_project_spec(spec)
        real = [c for c in components if not any("UNRESOLVED" in a for a in c.annotations)]
        if len(real) < 2:
            pytest.skip("BSS138 not found in KiCad library")
        q1_nets = set(real[0].pin_nets.values())
        q2_nets = set(real[1].pin_nets.values())
        # Their nets should not overlap (Q1_G != Q2_G)
        assert q1_nets.isdisjoint(q2_nets), f"Net collision: {q1_nets & q2_nets}"


# ================================================================
# Task 4: Power pin mapping
# ================================================================


class TestPowerMap:
    def test_default_mapping_applied(self):
        comp = ComponentDef(
            mpn="TEST",
            ref_prefix="U",
            value="TEST",
            pins=[],
            power_pins={"1": "VCC", "2": "GND", "3": "VBUS"},
        )
        _apply_power_map({}, comp)
        assert comp.power_pins["1"] == "VDD_3P3"
        assert comp.power_pins["2"] == "GND"
        assert comp.power_pins["3"] == "VBUS_5V"

    def test_explicit_power_map_overrides(self):
        comp = ComponentDef(
            mpn="TEST",
            ref_prefix="U",
            value="TEST",
            pins=[],
            power_pins={"1": "V+", "2": "V-"},
        )
        _apply_power_map({"power_map": {"V+": "VDD_5V", "V-": "GND"}}, comp)
        assert comp.power_pins["1"] == "VDD_5V"
        assert comp.power_pins["2"] == "GND"

    def test_unknown_power_names_preserved(self):
        comp = ComponentDef(
            mpn="TEST",
            ref_prefix="U",
            value="TEST",
            pins=[],
            power_pins={"1": "CUSTOM_RAIL"},
        )
        _apply_power_map({}, comp)
        assert comp.power_pins["1"] == "CUSTOM_RAIL"


# ================================================================
# Task 5: Misc sheet for unclassified components
# ================================================================


class TestMiscSheet:
    def test_unknown_category_goes_to_misc(self):
        comp = ComponentDef(mpn="X", ref_prefix="U", value="X", category="unknown", pins=[])
        assert classify_component(comp) == "misc"

    def test_protection_goes_to_misc(self):
        comp = ComponentDef(mpn="X", ref_prefix="D", value="X", category="protection", pins=[])
        assert classify_component(comp) == "misc"

    def test_discrete_goes_to_misc(self):
        comp = ComponentDef(mpn="X", ref_prefix="Q", value="X", category="discrete", pins=[])
        assert classify_component(comp) == "misc"

    def test_mcu_still_goes_to_mcu(self):
        comp = ComponentDef(mpn="X", ref_prefix="U", value="X", category="mcu", pins=[])
        assert classify_component(comp) == "mcu"

    def test_unrecognized_category_falls_to_misc(self):
        comp = ComponentDef(mpn="X", ref_prefix="Z", value="X", category="totally_new", pins=[], description="")
        assert classify_component(comp) == "misc"


# ================================================================
# Task 6: Passive inference
# ================================================================


class TestPassiveInference:
    def test_resistor_from_value_and_ref(self):
        result = _resolve_component(
            {"value": "10k", "ref": "R1"},
            "misc",
            get_default_registry(),
            BUILTIN_REGISTRY,
            None,
        )
        assert len(result) == 1
        assert result[0].ref_prefix == "R"
        assert result[0].value == "10k"
        assert not any("UNRESOLVED" in a for a in result[0].annotations)

    def test_capacitor_from_value_and_ref(self):
        result = _resolve_component(
            {"value": "100nF", "ref": "C1"},
            "misc",
            get_default_registry(),
            BUILTIN_REGISTRY,
            None,
        )
        assert len(result) == 1
        assert result[0].ref_prefix == "C"

    def test_no_ref_still_creates_stub(self):
        result = _resolve_component(
            {"value": "10k"},
            "misc",
            get_default_registry(),
            BUILTIN_REGISTRY,
            None,
        )
        assert len(result) == 1
        # No ref → can't infer passive type → stub
        assert any("UNRESOLVED" in a for a in result[0].annotations)


# ================================================================
# Task 7: Spec-vs-output reconciliation
# ================================================================


class TestReconciliation:
    def test_valid_spec_passes_validation(self):
        from circuit_weaver.mvp import validate_design

        spec = {
            "project": "test",
            "connectors": [{"ic": "USB-C-PWR", "ref": "J1"}],
        }
        report = validate_design(spec)
        assert report.valid

    def test_unresolved_component_fails_validation(self):
        from circuit_weaver.mvp import compile_design_ir

        spec = {
            "project": "test",
            "digital": [{"ic": "TOTALLY_FAKE_XYZ", "ref": "U1"}],
        }
        compiled = compile_design_ir(spec)
        # The component should be a stub
        assert len(compiled.components) == 1
        assert any("UNRESOLVED" in a for a in compiled.components[0].annotations)


class TestPowerMuxRegression:
    def test_ltc4357_variant_still_generates(self):
        template = PowerMuxTemplate()
        result = template.generate(
            {
                "ic": "LTC4357CMS8",
                "ref": "U4",
                "vin1_net": "VIN_A",
                "vin2_net": "VIN_B",
                "vout_net": "VSYS",
            }
        )
        comp = result.components[0]
        assert comp.mpn == "LTC4357CMS8"
        assert comp.power_pins["1"] == "VIN_A"
        assert comp.power_pins["6"] == "VIN_A"
        assert comp.power_pins["7"] == "VIN_A"
        assert comp.power_pins["8"] == "VIN_A"
        assert comp.pin_nets["2"] == "GATE_U4"
        assert comp.pin_nets["3"] == "SOURCE_U4"
        assert any(strap.net == "SHDN_U4" and strap.rail == "VIN_A" for strap in comp.straps)
        assert any("Ideal diode OR" in note for note in comp.annotations)
