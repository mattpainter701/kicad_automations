"""Dual-sided CPL export must use a reconciled physical PCB."""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from circuit_weaver.component_db import BypassCap, ComponentDef, StrapConfig
from circuit_weaver.design_ir import DesignIR
from circuit_weaver.design_loader import CompiledDesign
from circuit_weaver.dispatcher import _export_dual_cpl_artifacts
from circuit_weaver.jlcpcb_export import CplSourceError
from circuit_weaver.placement_pipeline import build_placement_inventory


def _compiled_design() -> CompiledDesign:
    controller = ComponentDef(
        mpn="CTRL-1",
        source_ref="U1",
        value="Controller",
        footprint="Package_QFN:QFN-16",
        bypass_caps=[
            BypassCap("1", "VDD", "GND", "100nF", "Capacitor_SMD:C_0402")
        ],
        straps=[
            StrapConfig("2", "BOOT", "GND", "10k", "Resistor_SMD:R_0402")
        ],
    )
    return CompiledDesign(
        ir=DesignIR(),
        components=[controller],
        metadata={"project": "PhysicalCpl"},
        engine_spec={},
    )


def _write_physical_board(
    path: Path,
    footprints: dict[str, str],
    *,
    override: dict[str, str] | None = None,
) -> None:
    override = override or {}
    blocks = []
    for index, (reference, identity) in enumerate(sorted(footprints.items())):
        blocks.append(
            f'''  (footprint "{override.get(reference, identity)}"
    (layer "{'F.Cu' if index % 2 == 0 else 'B.Cu'}")
    (at {10 + index} {20 + index} {90 * index})
    (property "Reference" "{reference}" (at 0 0 0))
    (pad "1" smd roundrect (at 0 0) (size 1 1) (layers "F.Cu" "F.Paste" "F.Mask"))
  )'''
        )
    path.write_text(
        '(kicad_pcb (version 20240108) (generator "pcbnew")\n'
        + "\n".join(blocks)
        + "\n)\n",
        encoding="utf-8",
    )


def _csv_refs(path: Path) -> set[str]:
    with path.open(newline="", encoding="utf-8") as handle:
        return {row["Designator"] for row in csv.DictReader(handle)}


def test_dual_cpl_uses_real_board_and_includes_generated_support_refs(tmp_path: Path) -> None:
    compiled = _compiled_design()
    inventory = build_placement_inventory(compiled.components)
    footprints = {item.reference: item.footprint for item in inventory.manifest.items}
    support_refs = {
        item.reference for item in inventory.manifest.items if item.source_kind in {"bypass", "strap"}
    }
    board = tmp_path / "physical.kicad_pcb"
    _write_physical_board(board, footprints)

    result = _export_dual_cpl_artifacts(
        compiled,
        tmp_path / "delivery",
        assembly_mode="dual-sided-sequential",
        pcb_path=board,
    )

    exported_refs = _csv_refs(Path(result["top_file"])) | _csv_refs(Path(result["bottom_file"]))
    assert exported_refs == set(inventory.references)
    assert support_refs <= exported_refs
    assert result["assembly_item_count"] == len(inventory.references)
    assert result["reference_reconciliation"]["exact_match"] is True
    assert result["pcb_source"] == str(board)


def test_dual_cpl_rejects_stale_board_footprint_before_writing(tmp_path: Path) -> None:
    compiled = _compiled_design()
    inventory = build_placement_inventory(compiled.components)
    footprints = {item.reference: item.footprint for item in inventory.manifest.items}
    board = tmp_path / "stale.kicad_pcb"
    _write_physical_board(board, footprints, override={"U1": "Package_QFN:QFN-32"})
    output = tmp_path / "delivery"

    with pytest.raises(CplSourceError, match="footprint identity mismatch.*U1"):
        _export_dual_cpl_artifacts(
            compiled,
            output,
            assembly_mode="dual-sided-sequential",
            pcb_path=board,
        )

    assert not (output / "cpl_top.csv").exists()
    assert not (output / "cpl_bottom.csv").exists()


def test_dual_cpl_rejects_board_missing_generated_support_ref(tmp_path: Path) -> None:
    compiled = _compiled_design()
    inventory = build_placement_inventory(compiled.components)
    footprints = {item.reference: item.footprint for item in inventory.manifest.items}
    footprints.pop(next(item.reference for item in inventory.manifest.items if item.source_kind == "strap"))
    board = tmp_path / "missing-support.kicad_pcb"
    _write_physical_board(board, footprints)

    with pytest.raises(CplSourceError, match="missing pad-bearing assembly refs"):
        _export_dual_cpl_artifacts(
            compiled,
            tmp_path / "delivery",
            assembly_mode="dual-sided-sequential",
            pcb_path=board,
        )

