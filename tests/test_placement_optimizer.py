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


def test_viewer_empty_components():
    from circuit_weaver.placement_viewer import generate_viewer

    html = generate_viewer([], {})
    assert "<!DOCTYPE html>" in html


# ---------- CLI integration tests ----------


def test_cli_optimize_placement_help():
    result = subprocess.run(
        [sys.executable, "-m", "circuit_weaver.mvp", "optimize-placement", "--help"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "optimize-placement" in result.stdout or "simulated annealing" in result.stdout


def test_cli_placement_viewer_help():
    result = subprocess.run(
        [sys.executable, "-m", "circuit_weaver.mvp", "placement-viewer", "--help"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "placement-viewer" in result.stdout or "interactive" in result.stdout
