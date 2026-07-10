"""Tests for placement_optimizer and placement_viewer modules."""

from __future__ import annotations

import json
import subprocess
import sys

from circuit_weaver.component_db import ComponentDef, PinDef


def _make_comp(ref: str, mpn: str = "", category: str = "digital", footprint: str = "QFN-32") -> ComponentDef:
    return ComponentDef(
        mpn=mpn or f"IC_{ref}",
        description=f"Test component {ref}",
        footprint=footprint,
        category=category,
        pins=[PinDef(number="1", name="VCC", electrical_type="power_in", side="L")],
        source_ref=ref,
    )


# ---------- placement_optimizer tests ----------


def test_optimize_empty_components():
    from circuit_weaver.placement_optimizer import PlacementConfig, optimize_placement

    result = optimize_placement([], config=PlacementConfig())
    assert result["status"] == "ok"
    assert result["placements"] == {}


def test_optimize_single_component():
    from circuit_weaver.placement_optimizer import PlacementConfig, optimize_placement

    comps = [_make_comp("U1", category="power")]
    result = optimize_placement(comps, config=PlacementConfig(iterations=100, seed=42))
    assert result["status"] == "ok"
    assert "U1" in result["placements"]
    p = result["placements"]["U1"]
    assert "x" in p and "y" in p and "rotation" in p and "layer" in p


def test_optimize_multiple_components():
    from circuit_weaver.placement_optimizer import PlacementConfig, optimize_placement

    comps = [
        _make_comp("U1", category="power"),
        _make_comp("U2", category="digital"),
        _make_comp("C1", category="passive", footprint="0402"),
        _make_comp("C2", category="passive", footprint="0402"),
        _make_comp("J1", category="connector", footprint="USB-C"),
    ]
    result = optimize_placement(comps, config=PlacementConfig(iterations=500, seed=42))
    assert result["status"] == "ok"
    assert len(result["placements"]) == 5
    # All within board bounds
    for ref, p in result["placements"].items():
        assert 0 < p["x"] < 100
        assert 0 < p["y"] < 80


def test_optimize_no_overlaps():
    from circuit_weaver.placement_optimizer import PlacementConfig, optimize_placement

    comps = [_make_comp(f"U{i}", category="digital", footprint="SOIC-8") for i in range(1, 8)]
    result = optimize_placement(comps, config=PlacementConfig(iterations=2000, seed=42))
    placements = result["placements"]

    # Check no two components have the exact same position
    positions = [(p["x"], p["y"]) for p in placements.values()]
    assert len(set(positions)) == len(positions), "Duplicate positions found"


def test_legalization_removes_physical_overlaps_even_without_sa():
    from circuit_weaver.placement_optimizer import PlacementConfig, optimize_placement

    comps = [_make_comp(f"U{i}", category="digital", footprint="SOIC-8") for i in range(1, 10)]
    result = optimize_placement(comps, config=PlacementConfig(strategy="simple"))

    assert result["quality"]["overlaps"] == []
    assert result["quality"]["legalization_moves"] > 0


def test_overlap_geometry_uses_rotated_dimensions():
    from circuit_weaver.placement_optimizer import ComponentPlacement, _overlap_area

    narrow_after_rotation = ComponentPlacement(
        ref="U1", x=10, y=10, width=10, height=2, rotation=90
    )
    neighbor = ComponentPlacement(ref="U2", x=13, y=10, width=2, height=2)

    assert _overlap_area(narrow_after_rotation, neighbor) == 0


def test_optimize_simple_strategy_skips_sa():
    from circuit_weaver.placement_optimizer import PlacementConfig, optimize_placement

    comps = [_make_comp("U1")]
    result = optimize_placement(comps, config=PlacementConfig(strategy="simple"))
    assert result["iterations"] == 0  # Simple skips SA
    assert result["strategy"] == "simple"


def test_optimize_thermal_strategy():
    from circuit_weaver.placement_optimizer import PlacementConfig, optimize_placement

    comps = [_make_comp("U1", category="power"), _make_comp("U2", category="power")]
    result = optimize_placement(comps, config=PlacementConfig(strategy="thermal", iterations=500, seed=42))
    assert result["strategy"] == "thermal"


def test_optimize_with_specs_dir(tmp_path):
    from circuit_weaver.placement_optimizer import PlacementConfig, optimize_placement

    specs_dir = tmp_path / "specs"
    specs_dir.mkdir()
    (specs_dir / "ic_thermal.json").write_text(
        json.dumps({"IC_U1": {"pdiss_max_w": 2.5, "type": "buck_converter"}}), encoding="utf-8"
    )
    (specs_dir / "si_params.json").write_text(
        json.dumps({"IC_U2": {"requires_impedance_control": True}}), encoding="utf-8"
    )

    comps = [_make_comp("U1", category="power"), _make_comp("U2", category="digital")]
    result = optimize_placement(comps, config=PlacementConfig(iterations=200, seed=42), specs_dir=str(specs_dir))
    assert result["status"] == "ok"


def test_optimize_thermal_warnings():
    from circuit_weaver.placement_optimizer import ComponentPlacement, PlacementConfig, _build_result

    state = [ComponentPlacement(ref="U1", x=50, y=40, thermal_dissipation_w=3.5)]
    result = _build_result(state, PlacementConfig(), 0, 0, 0)
    assert len(result["thermal_warnings"]) == 1
    assert "3.5W" in result["thermal_warnings"][0]


def test_optimize_deterministic_with_seed():
    from circuit_weaver.placement_optimizer import PlacementConfig, optimize_placement

    comps = [_make_comp(f"U{i}") for i in range(1, 6)]
    r1 = optimize_placement(comps, config=PlacementConfig(iterations=500, seed=123))
    r2 = optimize_placement(comps, config=PlacementConfig(iterations=500, seed=123))
    assert r1["placements"] == r2["placements"]


def test_optimize_connected_pair_settles_closer_than_unconnected_pair():
    from circuit_weaver.placement_optimizer import PlacementConfig, optimize_placement

    comps = [
        ComponentDef(
            mpn="IC_U1",
            description="Connected power block",
            footprint="QFN-32",
            category="power",
            pins=[PinDef(number="1", name="LINK", electrical_type="bidirectional", side="L")],
            pin_nets={"1": "CTRL_LINK"},
            source_ref="U1",
        ),
        ComponentDef(
            mpn="IC_U2",
            description="Connected digital block",
            footprint="QFN-32",
            category="digital",
            pins=[PinDef(number="1", name="LINK", electrical_type="bidirectional", side="L")],
            pin_nets={"1": "CTRL_LINK"},
            source_ref="U2",
        ),
        _make_comp("U3", category="power"),
        _make_comp("U4", category="digital"),
    ]
    result = optimize_placement(comps, config=PlacementConfig(strategy="balanced", iterations=1500, seed=42))
    placements = result["placements"]

    def _dist(a: str, b: str) -> float:
        dx = placements[a]["x"] - placements[b]["x"]
        dy = placements[a]["y"] - placements[b]["y"]
        return (dx * dx + dy * dy) ** 0.5

    assert _dist("U1", "U2") < _dist("U3", "U4")


def test_support_passive_starts_and_stays_near_owner():
    from circuit_weaver.placement_optimizer import PlacementConfig, optimize_placement

    owner = _make_comp("U1", category="digital", footprint="QFN-32")
    cap = _make_comp("C1", category="passive", footprint="0402")
    cap.placement_parent_ref = "U1"
    cap.placement_role = "decoupling"

    result = optimize_placement(
        [owner, cap],
        config=PlacementConfig(strategy="balanced", iterations=800, seed=42),
    )
    u1 = result["placements"]["U1"]
    c1 = result["placements"]["C1"]
    distance = ((u1["x"] - c1["x"]) ** 2 + (u1["y"] - c1["y"]) ** 2) ** 0.5

    assert distance < 6.0
    assert result["quality"]["missing_parents"] == []
    assert result["quality"]["support_body_violations"] == []
    assert result["quality"]["max_support_distance_mm"] < 6.0


def test_rf_and_usb_categories_have_explicit_edge_zones():
    from circuit_weaver.placement_optimizer import PlacementConfig, optimize_placement

    components = [
        _make_comp("U1", category="rf", footprint="QFN-32"),
        _make_comp("J1", category="usb", footprint="USB-C"),
    ]
    result = optimize_placement(components, config=PlacementConfig(strategy="simple"))

    rf = result["placements"]["U1"]
    usb = result["placements"]["J1"]
    assert rf["x"] > result["board_width_mm"] * 0.75
    assert rf["y"] < result["board_height_mm"] * 0.3
    assert usb["y"] > result["board_height_mm"] * 0.75


def test_machine_constraints_override_board_and_drive_fixed_edge_and_keepout_placement():
    from circuit_weaver.placement_optimizer import PlacementConfig, optimize_placement

    components = [_make_comp("U1"), _make_comp("U2")]
    result = optimize_placement(
        components,
        config=PlacementConfig(strategy="balanced", iterations=1200, seed=4),
        constraints=[
            {
                "kind": "placement",
                "target": "board",
                "board_width_mm": 50,
                "board_height_mm": 30,
            },
            {"kind": "placement", "target": "U1", "x_mm": 8, "y_mm": 8, "rotation": 90},
            {"kind": "placement", "target": "U2", "edge": "right"},
            {
                "kind": "keepout",
                "target": "middle",
                "x_mm": 20,
                "y_mm": 0,
                "width_mm": 10,
                "height_mm": 30,
            },
        ],
    )

    assert (result["board_width_mm"], result["board_height_mm"]) == (50, 30)
    assert {key: result["placements"]["U1"][key] for key in (
        "x",
        "y",
        "rotation",
        "layer",
        "locked",
        "constraint_locked",
        "width_mm",
        "height_mm",
    )} == {
        "x": 8.0,
        "y": 8.0,
        "rotation": 90.0,
        "layer": "front",
        "locked": True,
        "constraint_locked": True,
        "width_mm": 6.0,
        "height_mm": 6.0,
    }
    assert result["placements"]["U2"]["x"] == 46.0
    evaluation = result["constraint_evaluation"]
    assert evaluation["board_dimension_source"] == "constraints"
    assert evaluation["applied_count"] == 4
    assert evaluation["unsupported"] == []
    assert evaluation["violations"] == []


def test_unmachine_readable_placement_constraint_is_never_claimed_as_applied():
    from circuit_weaver.placement_optimizer import PlacementConfig, optimize_placement

    result = optimize_placement(
        [_make_comp("U1")],
        config=PlacementConfig(strategy="simple"),
        constraints=[
            {
                "kind": "placement",
                "target": "U1",
                "description": "Put this somewhere sensible near the enclosure opening",
            }
        ],
    )

    assert result["constraint_evaluation"]["applied_count"] == 0
    assert result["constraint_evaluation"]["unsupported"][0]["target"] == "U1"
    assert result["quality"]["review_required"] is True


def test_pin_relative_prose_is_blocked_without_pad_coordinates():
    from circuit_weaver.placement_optimizer import PlacementConfig, optimize_placement

    result = optimize_placement(
        [_make_comp("U1"), _make_comp("C1", category="passive", footprint="0402")],
        config=PlacementConfig(strategy="simple"),
        constraints=[
            {
                "kind": "placement",
                "target": "C1",
                "constraint": "within 3mm of U1 pin 5",
            }
        ],
    )

    unsupported = result["constraint_evaluation"]["unsupported"]
    assert unsupported and "pad coordinates" in unsupported[0]["reason"]


def test_balanced_strategy_compacts_disconnected_functional_islands():
    from circuit_weaver.placement_optimizer import PlacementConfig, optimize_placement

    components = [
        _make_comp("U1", category="power"),
        _make_comp("U2", category="digital"),
        _make_comp("U3", category="analog"),
        _make_comp("U4", category="comms"),
        _make_comp("U5", category="sensor"),
    ]
    simple = optimize_placement(components, config=PlacementConfig(strategy="simple", seed=7))
    balanced = optimize_placement(
        components,
        config=PlacementConfig(strategy="balanced", iterations=3000, seed=7),
    )

    def _area(result):
        xs = [placement["x"] for placement in result["placements"].values()]
        ys = [placement["y"] for placement in result["placements"].values()]
        return (max(xs) - min(xs)) * (max(ys) - min(ys))

    assert _area(balanced) < _area(simple) * 0.8
    assert balanced["quality"]["overlaps"] == []


def test_source_mpn_drives_thermal_metadata_and_shared_geometry(tmp_path):
    from circuit_weaver.placement_optimizer import (
        PlacementConfig,
        estimate_component_size,
        optimize_placement,
    )

    component = _make_comp("U1", mpn="REGISTRY_ALIAS", footprint="QFN-32")
    component.source_mpn = "REAL-MPN"
    specs = tmp_path / "specs"
    specs.mkdir()
    (specs / "ic_thermal.json").write_text(
        json.dumps({"REAL-MPN": {"pdiss_max_w": 2.5}}), encoding="utf-8"
    )

    result = optimize_placement(
        [component],
        config=PlacementConfig(strategy="simple"),
        specs_dir=specs,
    )

    assert estimate_component_size(component) == (6.0, 6.0)
    assert result["placements"]["U1"]["width_mm"] == 6.0
    assert result["thermal_warnings"] == [
        "U1: 2.5W dissipation — ensure adequate copper area"
    ]


def test_shared_geometry_parses_body_dimensions_and_known_module_connector_patterns():
    from circuit_weaver.placement_optimizer import estimate_footprint_size

    assert estimate_footprint_size("Package_LGA:Bosch_LGA-8_2.5x2.5mm", "U1") == (2.5, 2.5)
    assert estimate_footprint_size("RF_Module:ESP32-WROOM-32E", "U2") == (18.0, 25.5)
    assert estimate_footprint_size("Connector_USB:USB_C_Receptacle", "J1") == (9.0, 7.5)
    assert estimate_footprint_size("", "RP1") == (4.0, 3.0)


def test_unspecified_board_uses_compact_unverified_review_canvas():
    from circuit_weaver.placement_optimizer import PlacementConfig, optimize_placement

    components = [
        _make_comp("U1", footprint="RF_Module:ESP32-WROOM-32E"),
        _make_comp("U2", footprint="Package_LGA:Bosch_LGA-8_2.5x2.5mm"),
        _make_comp("J1", category="connector", footprint="Connector_USB:USB_C_Receptacle"),
    ] + [_make_comp(f"C{index}", category="passive", footprint="0402") for index in range(1, 13)]

    result = optimize_placement(
        components,
        config=PlacementConfig(strategy="simple"),
    )

    assert result["board_width_mm"] < 100
    assert result["board_height_mm"] < 80
    evaluation = result["constraint_evaluation"]
    assert evaluation["board_dimension_source"] == "derived_review"
    assert evaluation["effective_board"]["dimensions_verified"] is False


# ---------- placement_viewer tests ----------


def test_viewer_generates_html():
    from circuit_weaver.placement_viewer import generate_viewer

    comps = [_make_comp("U1", category="power"), _make_comp("C1", category="passive", footprint="0402")]
    placements = {
        "U1": {"x": 30, "y": 20, "rotation": 0, "layer": "front"},
        "C1": {"x": 35, "y": 25, "rotation": 90, "layer": "front"},
    }
    html = generate_viewer(comps, placements, board_width_mm=60, board_height_mm=40)
    assert "<!DOCTYPE html>" in html
    assert "U1" in html
    assert "C1" in html
    assert "PCB Placement Viewer" in html


def test_viewer_writes_file(tmp_path):
    from circuit_weaver.placement_viewer import generate_viewer

    comps = [_make_comp("U1")]
    placements = {"U1": {"x": 50, "y": 40, "rotation": 0, "layer": "front"}}
    out = tmp_path / "viewer.html"
    generate_viewer(comps, placements, output_path=out)
    assert out.exists()
    content = out.read_text(encoding="utf-8")
    assert "<!DOCTYPE html>" in content


def test_viewer_thermal_overlay():
    from circuit_weaver.placement_viewer import generate_viewer

    comps = [_make_comp("U1", category="power")]
    placements = {"U1": {"x": 50, "y": 40, "rotation": 0, "layer": "front"}}
    thermal = {"IC_U1": {"pdiss_max_w": 2.0}}
    html = generate_viewer(comps, placements, thermal_data=thermal)
    assert "thermal-overlay" in html or "Thermal" in html


def test_viewer_export_csv_button():
    from circuit_weaver.placement_viewer import generate_viewer

    comps = [_make_comp("U1")]
    placements = {"U1": {"x": 50, "y": 40, "rotation": 0, "layer": "front"}}
    html = generate_viewer(comps, placements)
    assert "Export CSV" in html
    assert "exportCSV" in html


def test_viewer_is_a_closed_loop_editor_not_a_static_preview():
    from circuit_weaver.placement_viewer import generate_viewer

    comps = [_make_comp("U1"), _make_comp("U2")]
    comps[0].pin_nets = {"1": "SHARED"}
    comps[1].pin_nets = {"1": "SHARED"}
    placements = {
        "U1": {"x": 20, "y": 20, "rotation": 0, "layer": "front"},
        "U2": {"x": 35, "y": 20, "rotation": 0, "layer": "front"},
    }

    html = generate_viewer(comps, placements)

    assert "pointerdown" in html
    assert "Drag to move" in html
    assert "Export JSON" in html
    assert "Export Editable SVG" in html
    assert "function exportSVG()" in html
    assert 'data-scale-px-per-mm="8.0"' in html
    assert 'data-layer="front"' in html
    assert "group.dataset.layer = c.layer" in html
    assert "const DESIGN_FINGERPRINT" in html
    assert "saved.design_fingerprint !== DESIGN_FINGERPRINT" in html
    assert "savedRefs.length !== currentRefs.length" in html
    assert "artifact_kind: 'placement_edits'" in html
    assert 'id="connections-layer"' in html
    assert 'id="net-select"' in html
    assert "updateQuality" in html


def test_viewer_embeds_placement_brief_and_official_references():
    from circuit_weaver.placement_viewer import generate_viewer

    comp = _make_comp("U1", category="power")
    context = {
        "authority": "Datasheet is authoritative.",
        "rules": [{"priority": "critical", "guidance": "Keep the hot loop short."}],
        "research_queries": [{"query": "U1 official layout"}],
        "references": [
            {
                "title": "Vendor layout guide",
                "url": "https://example.com/layout",
                "why": "Reference placement geometry.",
            }
        ],
    }
    html = generate_viewer(
        [comp],
        {"U1": {"x": 10, "y": 10, "rotation": 0, "layer": "front"}},
        placement_context=context,
    )

    assert "Placement brief" in html
    assert "Datasheet is authoritative" in html
    assert "Keep the hot loop short" in html
    assert "Vendor layout guide" in html


def test_viewer_renders_keepouts_hard_locks_and_readable_rotated_labels():
    from circuit_weaver.placement_viewer import generate_viewer

    component = _make_comp("U1")
    component.source_mpn = "REAL-MPN"
    html = generate_viewer(
        [component],
        {
            "U1": {
                "x": 8,
                "y": 8,
                "rotation": 180,
                "layer": "front",
                "locked": True,
                "constraint_locked": True,
                "width_mm": 6,
                "height_mm": 6,
            }
        },
        board_width_mm=50,
        board_height_mm=30,
        thermal_data={"REAL-MPN": {"pdiss_max_w": 2.0}},
        placement_context={
            "constraint_evaluation": {
                "applied": [{"kind": "fixed_position", "target": "U1"}],
                "keepouts": [
                    {
                        "id": "antenna",
                        "x_mm": 20,
                        "y_mm": 0,
                        "width_mm": 10,
                        "height_mm": 12,
                    }
                ],
            },
            "review_gate": {"status": "review_required", "blockers": []},
        },
    )

    assert 'id="constraints-layer"' in html
    assert 'data-keepout="antenna"' in html
    assert 'transform="rotate(-180)"' in html
    assert '"mpn": "REAL-MPN"' in html
    assert '"pdiss_w": 2.0' in html
    assert "if (COMPS[ref].constraint_locked) continue" in html
    assert "if (COMPS[selectedRef].constraint_locked) return" in html
    assert "components violate keepouts" in html


def test_viewer_storage_fingerprint_changes_with_board_or_constraints():
    import re

    from circuit_weaver.placement_viewer import generate_viewer

    component = _make_comp("U1")
    placements = {"U1": {"x": 8, "y": 8, "rotation": 0, "layer": "front"}}
    first = generate_viewer([component], placements, 40, 30)
    second = generate_viewer([component], placements, 50, 30)
    constrained = generate_viewer(
        [component],
        placements,
        40,
        30,
        placement_context={
            "constraint_evaluation": {
                "applied": [{"kind": "edge", "target": "U1", "edge": "left"}]
            }
        },
    )

    def _fingerprint(html: str) -> str:
        match = re.search(r"const DESIGN_FINGERPRINT = '([0-9a-f]+)'", html)
        assert match
        return match.group(1)

    assert len({_fingerprint(first), _fingerprint(second), _fingerprint(constrained)}) == 3


def test_viewer_empty_components():
    from circuit_weaver.placement_viewer import generate_viewer

    html = generate_viewer([], {})
    assert "<!DOCTYPE html>" in html


# ---------- CLI integration tests ----------


def test_cli_optimize_placement_help():
    result = subprocess.run(
        [sys.executable, "-m", "circuit_weaver.dispatcher", "optimize-placement", "--help"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "optimize-placement" in result.stdout or "simulated annealing" in result.stdout


def test_cli_placement_viewer_help():
    result = subprocess.run(
        [sys.executable, "-m", "circuit_weaver.dispatcher", "placement-viewer", "--help"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "placement-viewer" in result.stdout or "interactive" in result.stdout
