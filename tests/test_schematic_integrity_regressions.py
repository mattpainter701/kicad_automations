"""Regression coverage for fail-closed schematic generation invariants."""

from __future__ import annotations

import re

import pytest

from circuit_weaver.allocator import SheetAllocation, ensure_unique_sheet_names
from circuit_weaver.component_db import BUILTIN_REGISTRY, ComponentDef, PinDef
from circuit_weaver.generator import (
    _avoid_foreign_net_anchors,
    _normalize_polyline,
    _plan_power_flags,
    _render_sheet,
    _render_symbol_name_and_sexpr,
    _validate_rendered_pin_mappings,
    generate_from_components,
)
from circuit_weaver.placer import (
    PlacedComponent,
    SheetLayout,
    _component_ref,
    reserve_explicit_refs,
    reset_ref_counters,
)
from circuit_weaver.primitives import (
    _extract_sexpr_block,
    _resolve_label_collisions,
    get_pin_positions,
    pin_connection_point,
    sexpr_global_label,
    sexpr_wire,
)
from circuit_weaver.validator import _validate_pin_mapping_integrity


def _label_anchor(label: str) -> tuple[float, float]:
    match = re.search(r"\(at\s+([-\d.]+)\s+([-\d.]+)\s+\d+\)", label)
    assert match
    return float(match.group(1)), float(match.group(2))


def _wire_endpoints(wire: str) -> tuple[tuple[float, float], tuple[float, float]]:
    match = re.search(
        r"\(pts\s+\(xy\s+([-\d.]+)\s+([-\d.]+)\)\s+"
        r"\(xy\s+([-\d.]+)\s+([-\d.]+)\)\)",
        wire,
    )
    assert match
    return (
        (float(match.group(1)), float(match.group(2))),
        (float(match.group(3)), float(match.group(4))),
    )


def test_colliding_sheet_slugs_get_deterministic_unique_output_names():
    sheets = [
        SheetAllocation("mcu_a_b", "A-B", "A4"),
        SheetAllocation("MCU_A_B", "A B", "A4"),
        SheetAllocation("mcu_a_b", "A/B", "A4"),
    ]

    ensure_unique_sheet_names(sheets)

    assert [sheet.name for sheet in sheets] == ["mcu_a_b", "MCU_A_B_2", "mcu_a_b_3"]
    filenames = [f"{sheet.name}.kicad_sch".casefold() for sheet in sheets]
    assert len(filenames) == len(set(filenames))


def test_normalized_symbol_name_collision_keeps_wire_on_each_emitted_geometry():
    left_pin = ComponentDef(
        mpn="ABC-1",
        pins=[PinDef("1", "P", "input", "L")],
        pin_nets={"1": "LEFT_NET"},
    )
    right_pin = ComponentDef(
        mpn="ABC.1",
        pins=[PinDef("1", "P", "input", "R")],
        pin_nets={"1": "RIGHT_NET"},
    )
    layout = SheetLayout(
        "main",
        "Main",
        "A4",
        placed_ics=[
            PlacedComponent(left_pin, "U1", 50.8, 50.8),
            PlacedComponent(right_pin, "U2", 101.6, 50.8),
        ],
    )

    content = _render_sheet(layout, "collision", "", "root", "sheet", 1)
    instances = re.findall(
        r'\(symbol\s+\(lib_id\s+"([^"]+)"\)\s+'
        r"\(at\s+([-\d.]+)\s+([-\d.]+)\s+\d+\)",
        content,
    )
    assert len(instances) == 2
    assert instances[0][0] != instances[1][0]

    wire_starts = {
        _wire_endpoints(match.group(0))[0]
        for match in re.finditer(
            r"\(wire\s+\(pts\s+\(xy\s+[-\d.]+\s+[-\d.]+\)\s+"
            r"\(xy\s+[-\d.]+\s+[-\d.]+\)\).*?\n\s*\)",
            content,
            re.DOTALL,
        )
    }
    expected_starts = set()
    for lib_id, x, y in instances:
        definition_start = content.find(f'(symbol "{lib_id}"')
        assert definition_start >= 0
        definition = _extract_sexpr_block(content, definition_start)
        pin = get_pin_positions(definition, lib_id)["1"]
        expected = pin_connection_point(float(x), float(y), *pin[:4])
        expected_starts.add((round(expected[0], 2), round(expected[1], 2)))

    assert expected_starts <= wire_starts


def test_multi_label_fixed_point_never_detaches_labels_from_claimed_wires():
    anchors = [(10.16 + index * 1.27, 20.32) for index in range(4)]
    wires = [sexpr_wire(x + 7.62, y, x, y) for x, y in anchors]
    labels = [
        sexpr_global_label(x, y, f"VERY_LONG_COLLIDING_NET_{index}", 0)
        for index, (x, y) in enumerate(anchors)
    ]

    moved_labels, extended_wires = _resolve_label_collisions(labels, wires)

    assert any(_label_anchor(label) != anchor for label, anchor in zip(moved_labels, anchors))
    for label, wire in zip(moved_labels, extended_wires):
        assert _label_anchor(label) == _wire_endpoints(wire)[1]


def test_nonexistent_empty_and_overlapping_pin_maps_fail_closed():
    comp = ComponentDef(
        mpn="BROKEN-MAP",
        pins=[PinDef("1", "VALID", "input", "L")],
        pin_nets={"1": "", "99": "PHANTOM"},
        power_pins={"1": "VDD"},
        explicit_no_connects={"1", "100"},
    )

    issues = _validate_pin_mapping_integrity([comp])
    messages = "\n".join(issue.message for issue in issues)
    assert all(issue.level == "error" for issue in issues)
    assert "empty net names" in messages
    assert "both signal and power" in messages
    assert "both mapped and explicitly no-connect" in messages
    assert "99" in messages and "100" in messages

    symbol_name, symbol = _render_symbol_name_and_sexpr(comp)
    pin_positions = get_pin_positions(symbol, symbol_name)
    with pytest.raises(ValueError, match="Pin mapping integrity failed") as exc_info:
        _validate_rendered_pin_mappings(comp, pin_positions, "U1")
    rendered_error = str(exc_info.value)
    assert "empty signal nets" in rendered_error
    assert "both signal and power" in rendered_error
    assert "absent from emitted symbol" in rendered_error


def test_explicit_refs_are_reserved_before_anonymous_allocation():
    anonymous = ComponentDef(mpn="AUTO", ref_prefix="U")
    explicit = ComponentDef(mpn="FIXED", ref_prefix="U", source_ref="U1")

    reset_ref_counters()
    try:
        reserve_explicit_refs([anonymous, explicit])
        assert _component_ref(anonymous) == "U2"
        assert _component_ref(explicit) == "U1"
    finally:
        reset_ref_counters()


def test_power_flags_are_project_wide_and_skip_real_power_outputs():
    source = ComponentDef(
        mpn="SOURCE",
        pins=[
            PinDef("1", "VBUS", "power_out", "R"),
            PinDef("2", "GND", "power_in", "B"),
        ],
        power_pins={"1": "VBUS_5V", "2": "GND"},
    )
    remote_sink = ComponentDef(
        mpn="SINK",
        pins=[
            PinDef("1", "VIN", "power_in", "L"),
            PinDef("2", "GND", "power_in", "B"),
        ],
        power_pins={"1": "VBUS_5V", "2": "GND"},
    )
    layouts = [
        SheetLayout("source", "Source", "A4", placed_ics=[PlacedComponent(source, "J1", 50.8, 50.8)]),
        SheetLayout("sink", "Sink", "A4", placed_ics=[PlacedComponent(remote_sink, "U1", 50.8, 50.8)]),
    ]

    assert _plan_power_flags(layouts) == [{"GND"}, set()]


def test_marker_stub_never_lands_on_foreign_named_anchor():
    length = _avoid_foreign_net_anchors(
        "GND",
        10.16,
        10.16,
        90,
        6.35,
        [("VDD_3P3", 10.16, 16.51)],
    )

    assert length == pytest.approx(2.54)


def test_route_polyline_cancels_immediate_hairpin_backtracks():
    assert _normalize_polyline(
        [(0, 0), (1.27, 0), (0, 0), (0, 2.54)]
    ) == [(0.0, 0.0), (0.0, 2.54)]


def test_bme280_metadata_models_i2c_strap_and_real_kicad_footprint():
    bme = BUILTIN_REGISTRY.get("BME280")
    assert bme is not None
    assert bme.footprint == (
        "Package_LGA:Bosch_LGA-8_2.5x2.5mm_P0.65mm_ClockwisePinNumbering"
    )
    assert {pin.number: pin.electrical_type for pin in bme.pins}["5"] == "passive"


def test_generation_emits_portable_namespaced_project_symbol_library(tmp_path):
    component = ComponentDef(
        mpn="LOCAL-LIB",
        source_ref="U1",
        pins=[PinDef("1", "NC", "passive", "L")],
        explicit_no_connects={"1"},
    )

    files = generate_from_components(
        [component],
        output_dir=str(tmp_path),
        project_name="LocalLibrary",
        stable_uuids=True,
        validate=False,
        readiness_gate=False,
    )

    schematic = (tmp_path / "LocalLibrary.kicad_sch").read_text(encoding="utf-8")
    symbol_library = (tmp_path / "CircuitWeaver.kicad_sym").read_text(encoding="utf-8")
    symbol_table = (tmp_path / "sym-lib-table").read_text(encoding="utf-8")
    assert 'lib_id "CircuitWeaver:main__LOCAL_LIB"' in schematic
    assert '(symbol "CircuitWeaver:main__LOCAL_LIB"' in schematic
    assert '(symbol "main__LOCAL_LIB_1_1"' in schematic
    assert 'CircuitWeaver:main__LOCAL_LIB_1_1' not in schematic
    assert '(symbol "main__LOCAL_LIB"' in symbol_library
    assert '(symbol "main__LOCAL_LIB_1_1"' in symbol_library
    assert '${KIPRJMOD}/CircuitWeaver.kicad_sym' in symbol_table
    assert str(tmp_path / "CircuitWeaver.kicad_sym") in files
    assert str(tmp_path / "sym-lib-table") in files
    assert str(tmp_path / "LocalLibrary.kicad_pro") in files


def test_multisheet_library_scopes_same_named_symbols_and_root_project(tmp_path):
    components = [
        ComponentDef(
            mpn="SHARED",
            source_ref=f"U{index}",
            category="power" if index <= 5 else "sensor",
            pins=[PinDef("1", "NC", "passive", "L" if index <= 5 else "R")],
            explicit_no_connects={"1"},
        )
        for index in range(1, 10)
    ]

    files = generate_from_components(
        components,
        output_dir=str(tmp_path),
        project_name="ScopedLibrary",
        stable_uuids=True,
        hierarchical=True,
        validate=False,
        readiness_gate=False,
    )

    power_sheet = (tmp_path / "power.kicad_sch").read_text(encoding="utf-8")
    sensor_sheet = (tmp_path / "sensors.kicad_sch").read_text(encoding="utf-8")
    library = (tmp_path / "CircuitWeaver.kicad_sym").read_text(encoding="utf-8")
    root = (tmp_path / "ScopedLibrary.kicad_sch").read_text(encoding="utf-8")
    assert 'CircuitWeaver:power__SHARED' in power_sheet
    assert 'CircuitWeaver:sensors__SHARED' in sensor_sheet
    assert '(symbol "power__SHARED"' in library
    assert '(symbol "sensors__SHARED"' in library
    assert '(property "Sheetfile" "power.kicad_sch"' in root
    assert '(property "Sheetfile" "sensors.kicad_sch"' in root
    assert str(tmp_path / "ScopedLibrary.kicad_pro") in files
