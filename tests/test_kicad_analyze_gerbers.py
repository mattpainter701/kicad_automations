"""Truthfulness regressions for Gerber coordinate-system alignment."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
ANALYZER_PATH = REPO_ROOT / "skills" / "kicad" / "scripts" / "analyze_gerbers.py"
BUNDLED_ANALYZER_PATH = (
    REPO_ROOT
    / "src"
    / "circuit_weaver"
    / "_bundled_skills"
    / "kicad"
    / "scripts"
    / "analyze_gerbers.py"
)


def _load_analyzer() -> ModuleType:
    spec = importlib.util.spec_from_file_location("test_analyze_gerbers", ANALYZER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ANALYZER = _load_analyzer()


def _write_gerber(
    path: Path,
    *,
    file_function: str,
    coordinates: list[tuple[float, float]],
    same_coordinates: str | None = "Original",
) -> None:
    same_coordinates_line = ""
    if same_coordinates is not None:
        suffix = f",{same_coordinates}" if same_coordinates else ""
        same_coordinates_line = f"%TF.SameCoordinates{suffix}*%\n"
    operations = []
    for index, (x, y) in enumerate(coordinates):
        operation = "D02" if index == 0 else "D01"
        operations.append(f"X{round(x * 1_000_000)}Y{round(y * 1_000_000)}{operation}*")
    path.write_text(
        f"""%TF.FileFunction,{file_function}*%
{same_coordinates_line}%FSLAX46Y46*%
%MOMM*%
%ADD10C,0.100000*%
D10*
{chr(10).join(operations)}
M02*
""",
        encoding="utf-8",
    )


def _write_sparse_fixture(directory: Path, *, coordinate_ids: tuple[str | None, str | None, str | None]) -> None:
    directory.mkdir()
    _write_gerber(
        directory / "board-F_Cu.gtl",
        file_function="Copper,L1,Top",
        coordinates=[(9.5, -10), (10.5, -10), (20, -12.54)],
        same_coordinates=coordinate_ids[0],
    )
    _write_gerber(
        directory / "board-B_Cu.gbl",
        file_function="Copper,L2,Bot",
        coordinates=[(20, -10), (20, -12.54)],
        same_coordinates=coordinate_ids[1],
    )
    _write_gerber(
        directory / "board-Edge_Cuts.gm1",
        file_function="Profile,NP",
        coordinates=[(5, -5), (25, -5), (25, -20), (5, -20), (5, -5)],
        same_coordinates=coordinate_ids[2],
    )


def test_sparse_copper_uses_x2_declaration_not_artwork_dimensions(tmp_path: Path) -> None:
    gerbers = tmp_path / "gerbers"
    _write_sparse_fixture(gerbers, coordinate_ids=("Original", "Original", "Original"))

    alignment = ANALYZER.analyze_gerbers(str(gerbers))["alignment"]

    assert alignment["aligned"] is True
    assert alignment["status"] == "declared_aligned"
    assert alignment["method"] == "x2_same_coordinates"
    assert alignment["coordinate_system"] == "Original"
    assert alignment["issues"] == []
    assert alignment["layer_extents"]["F.Cu"]["width"] == 10.5
    assert alignment["layer_extents"]["B.Cu"]["width"] == 0
    assert alignment["layer_extents"]["Edge.Cuts"]["width"] == 20
    assert "not used as alignment evidence" in alignment["extent_note"]


@pytest.mark.parametrize(
    ("coordinate_ids", "method", "issue_fragment"),
    [
        (("Original", None, "Original"), "incomplete_x2_metadata", "missing from"),
        (("origin-a", "origin-b", "origin-a"), "conflicting_x2_metadata", "different"),
    ],
)
def test_incomplete_or_conflicting_x2_alignment_is_unknown(
    tmp_path: Path,
    coordinate_ids: tuple[str | None, str | None, str | None],
    method: str,
    issue_fragment: str,
) -> None:
    gerbers = tmp_path / "gerbers"
    _write_sparse_fixture(gerbers, coordinate_ids=coordinate_ids)

    alignment = ANALYZER.analyze_gerbers(str(gerbers))["alignment"]

    assert alignment["aligned"] is None
    assert alignment["status"] == "unknown"
    assert alignment["method"] == method
    assert issue_fragment in alignment["issues"][0]


def test_valueless_same_coordinates_and_matching_drill_declaration_are_supported(tmp_path: Path) -> None:
    front = tmp_path / "front.gtl"
    back = tmp_path / "back.gbl"
    drill = tmp_path / "board.drl"
    _write_gerber(
        front,
        file_function="Copper,L1,Top",
        coordinates=[(1, 1), (2, 2)],
        same_coordinates="",
    )
    _write_gerber(
        back,
        file_function="Copper,L2,Bot",
        coordinates=[(1, 1), (3, 3)],
        same_coordinates="",
    )
    drill.write_text(
        """M48
; #@! TF.SameCoordinates
; #@! TF.FileFunction,Plated,1,2,PTH
METRIC
T1C0.300
%
T1
X1.0Y1.0
M30
""",
        encoding="utf-8",
    )

    parsed_front = ANALYZER.parse_gerber(str(front))
    parsed_back = ANALYZER.parse_gerber(str(back))
    parsed_drill = ANALYZER.parse_drill(str(drill))
    alignment = ANALYZER.check_alignment([parsed_front, parsed_back], [parsed_drill])

    assert parsed_front["x2_attributes"]["SameCoordinates"] == ""
    assert parsed_drill["x2_attributes"]["SameCoordinates"] == ""
    assert alignment["aligned"] is True
    assert alignment["coordinate_system"] == ""
    assert alignment["drill_alignment"]["status"] == "declared_aligned"


def test_drill_without_same_coordinates_is_not_claimed_aligned() -> None:
    gerbers = [
        {
            "filename": "front.gtl",
            "layer_type": "F.Cu",
            "units": "mm",
            "coordinate_range": {"x_min": 0, "x_max": 1, "y_min": 0, "y_max": 1},
            "x2_attributes": {"SameCoordinates": "origin"},
        },
        {
            "filename": "back.gbl",
            "layer_type": "B.Cu",
            "units": "mm",
            "coordinate_range": {"x_min": 0, "x_max": 1, "y_min": 0, "y_max": 1},
            "x2_attributes": {"SameCoordinates": "origin"},
        },
    ]
    drills = [
        {
            "filename": "board.drl",
            "type": "PTH",
            "units": "mm",
            "coordinate_range": {"x_min": 0.5, "x_max": 0.5, "y_min": 0.5, "y_max": 0.5},
            "x2_attributes": {},
        }
    ]

    alignment = ANALYZER.check_alignment(gerbers, drills)

    assert alignment["aligned"] is True
    assert alignment["drill_alignment"]["status"] == "unknown"
    assert "do not all declare" in alignment["drill_alignment"]["reason"]


def test_packaged_analyzer_copy_is_identical() -> None:
    assert ANALYZER_PATH.read_bytes() == BUNDLED_ANALYZER_PATH.read_bytes()
