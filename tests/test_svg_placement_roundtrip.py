from __future__ import annotations

import math
from xml.etree import ElementTree as ET

import pytest

from circuit_weaver.svg_placement import (
    _parse_transform,
    export_placement_svg,
    import_placement_from_svg,
)


def test_export_keeps_reference_label_upright_without_changing_group_transform() -> None:
    svg_text = export_placement_svg(
        [{"ref": "U1", "footprint": "QFN-20", "category": "mcu"}],
        {"U1": {"x": 12.0, "y": 8.0, "rotation": 270, "layer": "front"}},
        40,
        30,
    )
    root = ET.fromstring(svg_text)
    namespace = {"svg": "http://www.w3.org/2000/svg"}
    group = root.find("svg:g[@data-ref='U1']", namespace)

    assert group is not None
    assert group.get("transform") == "translate(120.0, 80.0) rotate(270)"
    label = group.find("svg:text", namespace)
    assert label is not None
    assert label.get("transform") == "rotate(-270)"


def test_export_uses_shared_or_explicit_optimizer_geometry() -> None:
    svg_text = export_placement_svg(
        [
            {
                "ref": "U1",
                "footprint": "Package_LGA:Bosch_LGA-8_2.5x2.5mm",
                "category": "sensor",
            },
            {
                "ref": "U2",
                "footprint": "ignored",
                "category": "mcu",
                "width_mm": 18.0,
                "height_mm": 25.5,
            },
        ],
        {
            "U1": {"x": 5, "y": 5, "rotation": 0, "layer": "front"},
            "U2": {"x": 20, "y": 15, "rotation": 0, "layer": "front"},
        },
        40,
        30,
    )
    root = ET.fromstring(svg_text)
    namespace = {"svg": "http://www.w3.org/2000/svg"}
    u1 = root.find("svg:g[@data-ref='U1']/svg:rect", namespace)
    u2 = root.find("svg:g[@data-ref='U2']/svg:rect", namespace)

    assert u1 is not None and (u1.get("width"), u1.get("height")) == ("25.0", "25.0")
    assert u2 is not None and (u2.get("width"), u2.get("height")) == ("180.0", "255.0")


def test_parse_transform_accepts_standard_comma_matrix() -> None:
    assert _parse_transform("matrix(1,0,0,1,80,40)") == (80.0, 40.0, 0.0)


def test_import_composes_ancestor_and_component_transforms(tmp_path) -> None:
    svg = tmp_path / "edited.svg"
    svg.write_text(
        """<svg xmlns="http://www.w3.org/2000/svg" data-scale-px-per-mm="10">
        <g transform="translate(10,20)">
          <g data-ref="U1" data-layer="back" transform="matrix(0,1,-1,0,80,40)">
            <rect width="10" height="10"/>
          </g>
        </g>
        </svg>""",
        encoding="utf-8",
    )

    result = import_placement_from_svg(svg)

    assert result["U1"]["x"] == 9.0
    assert result["U1"]["y"] == 6.0
    assert math.isclose(result["U1"]["rotation"], 90.0)
    assert result["U1"]["layer"] == "back"


@pytest.mark.parametrize(
    "transform",
    ["", "matrix(1,0,broken,1,80,40)", "skewX(15)", "matrix(-1,0,0,1,80,40)"],
)
def test_malformed_or_unsafe_transform_fails_closed(tmp_path, transform: str) -> None:
    svg = tmp_path / "bad.svg"
    svg.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" data-scale-px-per-mm="10">'
        f'<g data-ref="U1" transform="{transform}"/></svg>',
        encoding="utf-8",
    )

    with pytest.raises(ValueError):
        import_placement_from_svg(svg)


def test_duplicate_component_reference_fails_closed(tmp_path) -> None:
    svg = tmp_path / "duplicate.svg"
    svg.write_text(
        """<svg xmlns="http://www.w3.org/2000/svg" data-scale-px-per-mm="10">
        <g data-ref="U1" transform="translate(10 10)"/>
        <g data-ref="U1" transform="translate(20 20)"/>
        </svg>""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="Duplicate"):
        import_placement_from_svg(svg)
