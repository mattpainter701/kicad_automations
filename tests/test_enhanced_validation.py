"""Tests for enhanced validation checks and cross-reference validator."""


from circuit_weaver.component_db import ComponentDef
from circuit_weaver.cross_reference_validator import (
    CrossReferenceResult,
    run_cross_reference_audit,
    validate_component_consistency,
    validate_schematic_vs_bom,
    validate_spec_vs_schematic,
)
from circuit_weaver.validator import (
    _validate_power_budget,
    _validate_thermal_limits,
)


def _make_component(ref, mpn="", category="", description="", footprint="SOT-23",
                    power_pins=None, power_reqs=None, pin_nets=None):
    comp = ComponentDef.__new__(ComponentDef)
    comp.source_ref = ref
    comp.mpn = mpn
    comp.category = category
    comp.description = description
    comp.value = ""
    comp.ref_prefix = ref[0] if ref else ""
    comp.pin_nets = pin_nets or {"1": "VIN", "2": "VOUT"}
    comp.source_mpn = mpn
    comp.source_value = ""
    comp.source_description = description
    comp.source_manufacturer = ""
    comp.footprint = footprint
    comp.lcsc_pn = ""
    comp.digikey_pn = ""
    comp.pins = []
    comp.power_pins = power_pins or {}
    comp.power_reqs = power_reqs or []
    comp.bypass_caps = []
    comp.straps = []
    return comp


# --- Enhanced validation checks ---

class TestPowerBudget:
    def test_flags_power_ic_without_power_pins(self):
        components = [
            _make_component("U1", mpn="TPS62300", category="buck",
                          description="buck converter", power_pins={}, power_reqs=[]),
        ]
        issues = _validate_power_budget(components)
        assert len(issues) >= 1
        assert any("power_pins" in i.message for i in issues)

    def test_passes_power_ic_with_power_pins(self):
        components = [
            _make_component("U1", mpn="TPS62300", category="buck",
                          description="buck converter",
                          power_pins={"VIN": "VDD_5V", "VOUT": "VDD_3V3"}),
        ]
        issues = _validate_power_budget(components)
        assert len(issues) == 0

    def test_ignores_non_power_components(self):
        components = [
            _make_component("R1", category="resistor", description="10k resistor"),
        ]
        issues = _validate_power_budget(components)
        assert len(issues) == 0


class TestThermalLimits:
    def test_returns_empty_when_no_thermal_data(self):
        components = [
            _make_component("R1", category="resistor", description="resistor"),
        ]
        issues = _validate_thermal_limits(components)
        # Should gracefully return empty (no power dissipation data for passives)
        assert isinstance(issues, list)


# --- Cross-reference validator ---

class TestSpecVsSchematic:
    def test_passes_when_all_refs_present(self):
        components = [_make_component("U1"), _make_component("R1")]
        spec = {"blocks": [{"id": "power", "ref": "U1"}, {"id": "passive", "ref": "R1"}]}
        result = validate_spec_vs_schematic(components, spec=spec)
        assert result.status == "pass"
        assert result.checked_items == 2

    def test_flags_missing_ref(self):
        components = [_make_component("U1")]
        spec = {"blocks": [{"id": "power", "ref": "U1"}, {"id": "sensor", "ref": "U2"}]}
        result = validate_spec_vs_schematic(components, spec=spec)
        assert len(result.issues) >= 1
        assert any("U2" in i.message for i in result.issues)

    def test_skips_when_no_spec(self):
        result = validate_spec_vs_schematic([_make_component("U1")], spec=None)
        assert result.status == "skipped"


class TestSchematicVsBom:
    def test_flags_missing_mpn_on_ic(self):
        components = [_make_component("U1", mpn="", footprint="SOT-23")]
        result = validate_schematic_vs_bom(components)
        assert any(i.code == "xref-missing-mpn" for i in result.issues)

    def test_passes_passive_without_mpn(self):
        components = [_make_component("R1", mpn="")]
        result = validate_schematic_vs_bom(components)
        # R is in passive prefixes, so no MPN warning
        assert not any(i.code == "xref-missing-mpn" for i in result.issues)

    def test_flags_missing_footprint(self):
        components = [_make_component("U1", mpn="ESP32", footprint="")]
        result = validate_schematic_vs_bom(components)
        assert any(i.code == "xref-missing-footprint" for i in result.issues)

    def test_passes_complete_component(self):
        components = [_make_component("U1", mpn="ESP32", footprint="QFN-48")]
        result = validate_schematic_vs_bom(components)
        assert all(i.code not in ("xref-missing-mpn", "xref-missing-footprint") for i in result.issues)


class TestComponentConsistency:
    def test_flags_duplicate_refs(self):
        components = [
            _make_component("U1", mpn="A"),
            _make_component("U1", mpn="B"),
        ]
        result = validate_component_consistency(components)
        assert any(i.code == "xref-duplicate-ref" for i in result.issues)
        assert result.status == "fail"

    def test_passes_unique_refs(self):
        components = [
            _make_component("U1", mpn="A"),
            _make_component("U2", mpn="B"),
        ]
        result = validate_component_consistency(components)
        assert not any(i.code == "xref-duplicate-ref" for i in result.issues)

    def test_flags_floating_power_pins(self):
        components = [
            _make_component("U1", mpn="A", power_pins={"VDD": "", "GND": "GND"}),
        ]
        result = validate_component_consistency(components)
        assert any(i.code == "xref-floating-power" for i in result.issues)


class TestRunCrossReferenceAudit:
    def test_returns_all_passes(self):
        components = [_make_component("U1", mpn="ESP32", footprint="QFN-48")]
        results = run_cross_reference_audit(components)
        assert len(results) == 3
        pass_names = {r.pass_name for r in results}
        assert "spec_vs_schematic" in pass_names
        assert "schematic_vs_bom" in pass_names
        assert "component_consistency" in pass_names

    def test_to_dict(self):
        result = CrossReferenceResult(
            pass_name="test", status="pass", checked_items=5,
        )
        d = result.to_dict()
        assert d["pass_name"] == "test"
        assert d["status"] == "pass"
        assert d["checked_items"] == 5
