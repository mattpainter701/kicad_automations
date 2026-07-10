from __future__ import annotations

import argparse
import json
import math
from xml.etree import ElementTree as ET

import pytest

from circuit_weaver import dispatcher, kicad_placement_api
from circuit_weaver.svg_placement import (
    _parse_transform,
    export_placement_svg,
    import_placement_from_svg,
    read_kicad_pcb_references,
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


def test_truncated_svg_is_rejected_against_complete_board_inventory(tmp_path) -> None:
    svg = tmp_path / "truncated.svg"
    svg.write_text(
        """<svg xmlns="http://www.w3.org/2000/svg" data-scale-px-per-mm="10">
        <g data-ref="U1" transform="translate(10 10)"/>
        </svg>""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match=r"missing board references: U2"):
        import_placement_from_svg(svg, known_refs={"U1", "U2"})


def test_partial_svg_requires_explicit_opt_in_and_still_rejects_unknown_refs(tmp_path) -> None:
    svg = tmp_path / "partial.svg"
    svg.write_text(
        """<svg xmlns="http://www.w3.org/2000/svg" data-scale-px-per-mm="10">
        <g data-ref="U1" transform="translate(10 10)"/>
        </svg>""",
        encoding="utf-8",
    )

    result = import_placement_from_svg(
        svg,
        known_refs={"U1", "U2"},
        allow_partial=True,
    )
    assert set(result) == {"U1"}

    unknown = tmp_path / "unknown.svg"
    unknown.write_text(
        """<svg xmlns="http://www.w3.org/2000/svg" data-scale-px-per-mm="10">
        <g data-ref="U3" transform="translate(10 10)"/>
        </svg>""",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match=r"unexpected SVG references: U3"):
        import_placement_from_svg(
            unknown,
            known_refs={"U1", "U2"},
            allow_partial=True,
        )


def test_board_reference_inventory_supports_modern_and_legacy_kicad_refs(tmp_path) -> None:
    board = tmp_path / "board.kicad_pcb"
    board.write_text(
        """(kicad_pcb
          (footprint "Package:One" (layer "F.Cu")
            (property "Reference" "U1") (at 1 2))
          (footprint "Package:Two" (layer "F.Cu")
            (fp_text reference "U2") (at 3 4)))
        """,
        encoding="utf-8",
    )

    assert read_kicad_pcb_references(board) == {"U1", "U2"}


def test_import_placement_cli_rejects_truncated_svg_before_board_update(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    board = tmp_path / "board.kicad_pcb"
    board.write_text(
        """(kicad_pcb
          (footprint "Package:One" (layer "F.Cu")
            (property "Reference" "U1") (at 1 2 0))
          (footprint "Package:Two" (layer "F.Cu")
            (property "Reference" "U2") (at 3 4 0)))
        """,
        encoding="utf-8",
    )
    svg = tmp_path / "truncated.svg"
    svg.write_text(
        """<svg xmlns="http://www.w3.org/2000/svg" data-scale-px-per-mm="10">
        <g data-ref="U1" transform="translate(10 20)"/>
        </svg>""",
        encoding="utf-8",
    )
    before = board.read_text(encoding="utf-8")
    monkeypatch.setattr(
        kicad_placement_api,
        "check_kicad_available",
        lambda: (False, "test fallback"),
    )
    args = argparse.Namespace(
        command="import-placement",
        svg=str(svg),
        kicad_pcb=str(board),
        output_pcb=None,
        output_cpl=None,
        dry_run=True,
        allow_partial=False,
    )

    with pytest.raises(SystemExit) as exc_info:
        dispatcher._main_dispatch(args, lambda *_args, **_kwargs: None)

    assert exc_info.value.code == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "error"
    assert "missing board references: U2" in payload["message"]
    assert board.read_text(encoding="utf-8") == before


def test_import_placement_cli_partial_opt_in_reports_omitted_board_refs(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    board = tmp_path / "board.kicad_pcb"
    board.write_text(
        """(kicad_pcb
          (footprint "Package:One" (layer "F.Cu")
            (property "Reference" "U1") (at 1 2 0))
          (footprint "Package:Two" (layer "F.Cu")
            (property "Reference" "U2") (at 3 4 0)))
        """,
        encoding="utf-8",
    )
    svg = tmp_path / "partial.svg"
    svg.write_text(
        """<svg xmlns="http://www.w3.org/2000/svg" data-scale-px-per-mm="10">
        <g data-ref="U1" transform="translate(50 60)"/>
        </svg>""",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        kicad_placement_api,
        "check_kicad_available",
        lambda: (False, "test fallback"),
    )
    args = argparse.Namespace(
        command="import-placement",
        svg=str(svg),
        kicad_pcb=str(board),
        output_pcb=None,
        output_cpl=None,
        dry_run=True,
        allow_partial=True,
    )

    with pytest.raises(SystemExit) as exc_info:
        dispatcher._main_dispatch(args, lambda *_args, **_kwargs: None)

    assert exc_info.value.code == 0
    payload = json.loads(capsys.readouterr().out)
    reconciliation = payload["reference_reconciliation"]
    assert reconciliation["mode"] == "partial_opt_in"
    assert reconciliation["exact_match"] is False
    assert reconciliation["missing_from_svg"] == ["U2"]
    assert payload["kicad_pcb"]["updated"] == 1
