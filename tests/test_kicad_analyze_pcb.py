"""Truthfulness regressions for the bundled KiCad PCB analyzer."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
ANALYZER = REPO_ROOT / "skills" / "kicad" / "scripts" / "analyze_pcb.py"


def _run_analyzer(pcb: Path) -> dict:
    completed = subprocess.run(
        [sys.executable, str(ANALYZER), str(pcb), "--compact"],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout)


def _analyze(tmp_path: Path, board: str) -> dict:
    pcb = tmp_path / "board.kicad_pcb"
    pcb.write_text(board, encoding="utf-8")
    return _run_analyzer(pcb)


def test_padless_circuit_weaver_preview_is_review_only_and_incomplete(tmp_path: Path) -> None:
    result = _analyze(
        tmp_path,
        """(kicad_pcb (version 20240108) (generator "schematic_engine placement_preview")
  (net 0 "")
  (net 1 "GND")
  (footprint "CircuitWeaver:PlacementOutline" (layer "F.Cu") (at 10 10)
    (property "Reference" "U1")
    (property "Value" "MCU")
  )
)
""",
    )

    assert result["source_generator"] == "schematic_engine placement_preview"
    assert result["connectivity"]["routing_complete"] is False
    assert result["connectivity"]["routing_status"] == "incomplete"
    assert result["statistics"]["pad_count"] == 0
    assert result["statistics"]["routable_net_count"] == 0
    assert result["statistics"]["routing_complete"] is False
    assert result["statistics"]["routing_status"] == "incomplete"
    assert result["statistics"]["routable"] is False
    assert result["statistics"]["review_only"] is True
    assert result["statistics"]["has_copper"] is False
    assert result["statistics"]["copper_item_count"] == 0
    assert result["status"] == "review_only"
    assert result["kicad_verified"] is False
    assert result["verification_status"] == "unverified"
    assert "does not run kicad-cli" in result["verification_reason"]
    assert result["routing_assessment"] == {
        "status": "review_only",
        "classification": "placement_preview",
        "routable": False,
        "review_only": True,
        "workflow": "review_only",
        "placement_preview": True,
        "routing_complete": False,
        "routing_status": "incomplete",
        "pad_count": 0,
        "routable_net_count": 0,
        "has_copper": False,
        "copper_item_count": 0,
        "source_generator": "schematic_engine placement_preview",
        "kicad_verified": False,
        "verification_status": "unverified",
        "verification_reason": (
            "Static S-expression analysis does not run kicad-cli; KiCad loadability and DRC remain unverified."
        ),
        "reason": (
            "Circuit Weaver placement previews are review-only and contain no authoritative pads or routable "
            "connectivity. Forward-annotate the schematic into a real KiCad PCB before routing."
        ),
    }


def test_generated_circuit_weaver_placement_is_not_routing_success(tmp_path: Path) -> None:
    from circuit_weaver.component_db import ComponentDef, PinDef
    from circuit_weaver.pcb_export import generate_pcb_placement

    component = ComponentDef(
        mpn="TEST_U1",
        ref_prefix="U",
        source_ref="U1",
        value="TEST",
        footprint="Package_DFN_QFN:QFN-16-1EP_3x3mm_P0.5mm_EP1.7x1.7mm",
        category="digital",
        pins=[
            PinDef("1", "SIG", "bidirectional", "L"),
            PinDef("2", "VDD", "power_in", "T"),
            PinDef("3", "GND", "power_in", "B"),
        ],
        power_pins={"2": "VDD_3P3", "3": "GND"},
    )
    pcb, _ = generate_pcb_placement([component], tmp_path, "Preview")

    result = _run_analyzer(pcb)

    assert result["source_generator"] == "schematic_engine placement_preview"
    assert result["routing_assessment"]["classification"] == "placement_preview"
    assert result["routing_assessment"]["routable"] is False
    assert result["routing_assessment"]["review_only"] is True
    assert result["routing_assessment"]["has_copper"] is False
    assert result["statistics"]["pad_count"] == 0
    assert result["statistics"]["routing_complete"] is False
    assert result["status"] == "review_only"
    assert result["kicad_verified"] is False
    assert result["verification_status"] == "unverified"


def test_zero_copper_board_is_incomplete_and_unverified(tmp_path: Path) -> None:
    result = _analyze(
        tmp_path,
        """(kicad_pcb (version 20240108) (generator "pcbnew")
  (layers (0 "F.Cu" signal) (31 "B.Cu" signal))
  (net 0 "")
  (net 1 "SIG")
  (footprint "Test:Pad" (layer "F.Cu") (at 10 10)
    (property "Reference" "J1")
    (property "Value" "TEST")
    (pad "1" smd rect (at 0 0) (size 1 1) (layers "F.Cu") (net 1 "SIG"))
  )
  (footprint "Test:Pad" (layer "F.Cu") (at 20 10)
    (property "Reference" "J2")
    (property "Value" "TEST")
    (pad "1" smd rect (at 0 0) (size 1 1) (layers "F.Cu") (net 1 "SIG"))
  )
)
""",
    )

    assessment = result["routing_assessment"]
    assert assessment["classification"] == "routable_board"
    assert assessment["routable"] is True
    assert assessment["review_only"] is False
    assert assessment["has_copper"] is False
    assert assessment["copper_item_count"] == 0
    assert assessment["routing_complete"] is False
    assert assessment["status"] == "incomplete"
    assert result["status"] == "incomplete"
    assert result["kicad_verified"] is False
    assert result["verification_status"] == "unverified"


def test_legitimate_routed_board_remains_complete(tmp_path: Path) -> None:
    result = _analyze(
        tmp_path,
        """(kicad_pcb (version 20240108) (generator "pcbnew")
  (layers (0 "F.Cu" signal) (31 "B.Cu" signal))
  (net 0 "")
  (net 1 "SIG")
  (footprint "Test:Pad" (layer "F.Cu") (at 10 10)
    (property "Reference" "J1")
    (property "Value" "TEST")
    (pad "1" smd rect (at 0 0) (size 1 1) (layers "F.Cu") (net 1 "SIG"))
  )
  (footprint "Test:Pad" (layer "F.Cu") (at 20 10)
    (property "Reference" "J2")
    (property "Value" "TEST")
    (pad "1" smd rect (at 0 0) (size 1 1) (layers "F.Cu") (net 1 "SIG"))
  )
  (segment (start 10 10) (end 20 10) (width 0.25) (layer "F.Cu") (net 1))
)
""",
    )

    assert result["routing_assessment"]["classification"] == "routable_board"
    assert result["routing_assessment"]["routable"] is True
    assert result["routing_assessment"]["review_only"] is False
    assert result["routing_assessment"]["has_copper"] is True
    assert result["routing_assessment"]["routing_complete"] is True
    assert result["status"] == "complete_unverified"
    assert result["kicad_verified"] is False
    assert result["verification_status"] == "unverified"
    assert result["statistics"]["routing_complete"] is True
    assert result["connectivity"]["routing_complete"] is True
