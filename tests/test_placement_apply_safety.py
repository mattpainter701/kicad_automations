from __future__ import annotations

import sys
from types import SimpleNamespace
from unittest.mock import patch

from circuit_weaver.kicad_placement_api import update_board_placements
from circuit_weaver.svg_placement import update_kicad_pcb_placements

PCB = """(kicad_pcb (version 20240108)
  (footprint "Package:Part" (layer "F.Cu") (at 1 2 0)
    (property "Reference" "U1")
    (pad "1" smd rect (at 0 0) (size 1 1) (layers "F.Cu"))
  )
)
"""


def test_regex_dry_run_never_writes_input(tmp_path) -> None:
    board = tmp_path / "board.kicad_pcb"
    board.write_text(PCB, encoding="utf-8")
    before = board.read_bytes()

    result = update_kicad_pcb_placements(
        board,
        {"U1": {"x": 10, "y": 20, "rotation": 90, "layer": "front"}},
        use_api=False,
        dry_run=True,
    )

    assert result["success"] is True
    assert result["dry_run"] is True
    assert board.read_bytes() == before


def test_regex_fallback_blocks_layer_flip_without_partial_write(tmp_path) -> None:
    board = tmp_path / "board.kicad_pcb"
    output = tmp_path / "updated.kicad_pcb"
    board.write_text(PCB, encoding="utf-8")

    result = update_kicad_pcb_placements(
        board,
        {"U1": {"x": 10, "y": 20, "rotation": 90, "layer": "back"}},
        output_path=output,
        use_api=False,
    )

    assert result["success"] is False
    assert "cannot safely flip" in result["errors"][0]
    assert not output.exists()


def test_regex_fallback_updates_balanced_footprint_atomically(tmp_path) -> None:
    board = tmp_path / "board.kicad_pcb"
    output = tmp_path / "updated.kicad_pcb"
    board.write_text(PCB, encoding="utf-8")

    result = update_kicad_pcb_placements(
        board,
        {"U1": {"x": 10, "y": 20, "rotation": 90, "layer": "front"}},
        output_path=output,
        use_api=False,
    )

    assert result["success"] is True
    assert "(at 10 20 90)" in output.read_text(encoding="utf-8")


class _Footprint:
    def __init__(self, layer: int) -> None:
        self.layer = layer
        self.flips = 0
        self.position = None
        self.orientation = None

    def GetLayer(self):
        return self.layer

    def Flip(self, _position, _around_x):
        self.flips += 1
        self.layer = 0 if self.layer == 31 else 31

    def SetPosition(self, position):
        self.position = position

    def SetOrientation(self, orientation):
        self.orientation = orientation


class _Board:
    def __init__(self, footprint: _Footprint) -> None:
        self.footprint = footprint
        self.saved: list[str] = []

    def FindFootprintByReference(self, ref):
        return self.footprint if ref == "U1" else None

    def Save(self, path):
        self.saved.append(path)


def _fake_pcbnew(board: _Board):
    return SimpleNamespace(
        F_Cu=0,
        B_Cu=31,
        TENTHS_OF_A_DEGREE=1,
        LoadBoard=lambda _path: board,
        VECTOR2I=lambda x, y: (x, y),
        EDA_ANGLE=lambda value, _unit: value,
    )


def test_pcbnew_layer_application_is_idempotent_and_dry_run_does_not_save(tmp_path) -> None:
    footprint = _Footprint(layer=31)
    board = _Board(footprint)
    fake = _fake_pcbnew(board)
    placement = {"U1": {"x": 10, "y": 20, "rotation": 90, "layer": "back"}}

    with patch("circuit_weaver.kicad_placement_api.check_kicad_available", return_value=(True, "ok")):
        with patch.dict(sys.modules, {"pcbnew": fake}):
            result = update_board_placements(tmp_path / "board.kicad_pcb", placement, dry_run=True)

    assert result["success"] is True
    assert footprint.flips == 0
    assert board.saved == []


def test_pcbnew_flips_only_when_requested_side_differs(tmp_path) -> None:
    footprint = _Footprint(layer=31)
    board = _Board(footprint)
    fake = _fake_pcbnew(board)
    placement = {"U1": {"x": 10, "y": 20, "rotation": 90, "layer": "front"}}

    with patch("circuit_weaver.kicad_placement_api.check_kicad_available", return_value=(True, "ok")):
        with patch.dict(sys.modules, {"pcbnew": fake}):
            result = update_board_placements(tmp_path / "board.kicad_pcb", placement, dry_run=True)

    assert result["success"] is True
    assert footprint.flips == 1
    assert footprint.layer == 0


def test_wrapper_propagates_dry_run_to_pcbnew_api(tmp_path) -> None:
    with patch("circuit_weaver.kicad_placement_api.update_board_placements") as update:
        update.return_value = {"success": True, "updated": ["U1"], "not_found": [], "errors": []}
        update_kicad_pcb_placements(
            tmp_path / "board.kicad_pcb",
            {"U1": {"x": 1, "y": 2, "rotation": 0, "layer": "front"}},
            use_api=True,
            dry_run=True,
        )

    assert update.call_args.kwargs["dry_run"] is True
