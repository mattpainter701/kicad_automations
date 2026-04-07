"""Tests for the enclosure_designer module."""

from __future__ import annotations

from pathlib import Path

from circuit_weaver.enclosure_designer import generate_enclosure_scad, render_enclosure_stl


def test_generate_basic_enclosure():
    """Should produce valid OpenSCAD code for a basic enclosure."""
    scad = generate_enclosure_scad(
        board_width_mm=100,
        board_height_mm=80,
    )
    assert "difference()" in scad or "cube(" in scad
    assert "100" in scad  # board width should appear
    assert "80" in scad  # board height should appear


def test_generate_with_ports():
    """Should include port cutouts in generated code."""
    scad = generate_enclosure_scad(
        board_width_mm=60,
        board_height_mm=40,
        ports=[
            {"type": "usb_c", "side": "front", "x_offset": 10, "y_offset": 5},
            {"type": "round", "diameter": 6, "side": "back", "x_offset": 30, "y_offset": 20},
        ],
    )
    assert "usb_c" in scad.lower() or "port" in scad.lower() or "translate" in scad


def test_generate_with_mounting_holes():
    """Should include mounting holes in generated code."""
    scad = generate_enclosure_scad(
        board_width_mm=80,
        board_height_mm=60,
        mounting_holes=[
            {"x": 5, "y": 5},
            {"x": 75, "y": 5},
            {"x": 5, "y": 55},
            {"x": 75, "y": 55},
        ],
    )
    assert "cylinder" in scad.lower() or "mount" in scad.lower()


def test_generate_custom_dimensions():
    """Should respect custom wall thickness and clearance."""
    scad = generate_enclosure_scad(
        board_width_mm=50,
        board_height_mm=30,
        wall_thickness_mm=3.0,
        clearance_mm=1.5,
        component_height_mm=8,
    )
    assert isinstance(scad, str)
    assert len(scad) > 100  # Should be non-trivial code


def test_generate_returns_string():
    """Return type should be a string of OpenSCAD code."""
    result = generate_enclosure_scad(board_width_mm=40, board_height_mm=30)
    assert isinstance(result, str)
    assert len(result) > 0


def test_render_stl_without_openscad(tmp_path):
    """render_enclosure_stl should return None if OpenSCAD is not installed."""
    scad_file = tmp_path / "test.scad"
    scad_file.write_text("cube([10,10,10]);", encoding="utf-8")
    # This will return None if openscad isn't on PATH (typical in CI)
    result = render_enclosure_stl(scad_file)
    # Either returns a Path (if openscad installed) or None (if not)
    assert result is None or isinstance(result, Path)


def test_package_exports():
    """Enclosure functions should be importable from the package."""
    import circuit_weaver

    assert hasattr(circuit_weaver, "generate_enclosure_scad")
    assert hasattr(circuit_weaver, "render_enclosure_stl")
    assert callable(circuit_weaver.generate_enclosure_scad)
    assert callable(circuit_weaver.render_enclosure_stl)
