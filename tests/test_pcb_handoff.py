"""T249 authoritative schematic-to-PCB handoff contracts."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

import circuit_weaver.pcb_handoff as pcb_handoff
from circuit_weaver.component_db import ComponentDef, PinDef
from circuit_weaver.footprint_lib import KiCadFootprintLibrary
from circuit_weaver.identity import (
    IdentityHandoffBlocked,
    IdentityHandoffBundle,
    PinPadMap,
    build_identity_record,
    build_identity_source_assertion,
    reconcile_identity_assertions,
)
from circuit_weaver.pcb_contracts import PcbArtifactKind, PcbConstraint, inspect_pcb_artifact
from circuit_weaver.pcb_handoff import approve_placements, generate_authoritative_board

FOOTPRINT = """(footprint "TEST_2PAD"
  (version 20240108)
  (generator pcbnew)
  (layer "F.Cu")
  (fp_rect (start -2 -1) (end 2 1) (stroke (width 0.05) (type default)) (fill none) (layer "F.CrtYd"))
  (pad "1" smd rect (at -1 0) (size 1 1) (layers "F.Cu" "F.Paste" "F.Mask"))
  (pad "2" smd rect (at 1 0) (size 1 1) (layers "F.Cu" "F.Paste" "F.Mask"))
)"""


def _library(tmp_path: Path) -> KiCadFootprintLibrary:
    pretty = tmp_path / "Test.pretty"
    pretty.mkdir(parents=True)
    (pretty / "TEST_2PAD.kicad_mod").write_text(FOOTPRINT, encoding="utf-8")
    return KiCadFootprintLibrary(tmp_path)


def _component() -> ComponentDef:
    return ComponentDef(
        mpn="ACME-2P",
        source_mpn="ACME-2P",
        source_ref="U1",
        source_manufacturer="Acme",
        value="ACME-2P",
        footprint="Test:TEST_2PAD",
        pins=[PinDef("1", "SIG", "bidirectional", "L"), PinDef("2", "GND", "power_in", "B")],
        pin_nets={"1": "SIG"},
        power_pins={"2": "GND"},
    )


def _identity():
    return build_identity_record(
        status="resolved",
        manufacturer="Acme",
        mpn="ACME-2P",
        package_suffix="2P",
        symbol_ref="Acme:ACME-2P",
        footprint_ref="Test:TEST_2PAD",
        symbol_pins=("1", "2"),
        footprint_pads=("1", "2"),
        pin_pad_map=(PinPadMap("1", "1"), PinPadMap("2", "2")),
        evidence_ids=("EV-DATASHEET-0123456789ab",),
    )


def _assertion(identity, family: str, document: str):
    return build_identity_source_assertion(
        source_family=family,
        source_uri=f"https://example.test/{document}",
        source_doc_id=document,
        identity=identity,
        evidence_ids=("EV-DATASHEET-0123456789ab",),
    )


def _bundle(*, independent: bool = True) -> IdentityHandoffBundle:
    identity = _identity()
    assertions = [_assertion(identity, "manufacturer", "datasheet")]
    if independent:
        assertions.append(_assertion(identity, "footprint", "library"))
    return IdentityHandoffBundle(
        assertions=tuple(assertions),
        reconciliation=reconcile_identity_assertions(assertions),
        manufacturer="Acme",
        mpn="ACME-2P",
        package_suffix="2P",
        symbol_ref="Acme:ACME-2P",
        footprint_ref="Test:TEST_2PAD",
    )


def _approval(placements, approval_id="PLA-0123456789ab"):
    return approve_placements(
        placements,
        approval_id=approval_id,
        approved_at="2026-01-01T00:00:00Z",
        expires_at="2100-01-01T00:00:00Z",
    )


def _constraints():
    return (
        PcbConstraint.create(
            klass="clearance",
            target="net:SIG",
            params={"minimum": {"value": 0.2, "unit": "mm"}},
            origin="user",
            evidence_ids=("EV-DATASHEET-0123456789ab",),
        ),
    )


def test_authoritative_handoff_emits_real_pads_nets_geometry_and_provenance(tmp_path: Path) -> None:
    output = tmp_path / "out"
    placements = {"U1": {"x_mm": 20, "y_mm": 15, "rotation_deg": 90, "layer": "F.Cu"}}
    result = generate_authoritative_board(
        [_component()],
        placements,
        {"U1": _bundle()},
        output,
        project_name="RealBoard",
        placement_approval=_approval(placements),
        board_constraints=_constraints(),
        footprint_library=_library(tmp_path / "libs"),
    )

    board_path = Path(result.board_path)
    board = board_path.read_text(encoding="utf-8")
    inspection = inspect_pcb_artifact(board_path)
    manifest = json.loads(Path(result.board_manifest_path).read_text(encoding="utf-8"))
    evidence = json.loads(Path(result.evidence_manifest_path).read_text(encoding="utf-8"))

    assert inspection.kind is PcbArtifactKind.AUTHORITATIVE
    assert result.pad_count == 2
    assert '(footprint "Test:TEST_2PAD"' in board
    assert '(pad "1"' in board and '(net 2 "SIG")' in board
    assert '(pad "2"' in board and '(net 1 "GND")' in board
    assert "placement_preview" not in board
    assert manifest["components"][0]["geometry"] == {
        "height_mm": 2.0,
        "source": "courtyard",
        "width_mm": 4.0,
    }
    assert manifest["board_provenance_evidence_id"] == result.board_provenance_evidence_id
    provenance = next(item for item in evidence["records"] if item["id"] == result.board_provenance_evidence_id)
    assert provenance["subject_ref"] == "tool:pcb_handoff"
    assert provenance["kind"] == "tool_result"
    assert "PLA-0123456789ab" in provenance["claim"]
    assert result.identity_guard_ids[0] in provenance["claim"]


def test_authoritative_rerun_preserves_uuid_and_reports_semantic_change(tmp_path: Path) -> None:
    library = _library(tmp_path / "libs")
    output = tmp_path / "out"
    kwargs = {
        "components": [_component()],
        "identity_handoffs": {"U1": _bundle()},
        "output_dir": output,
        "project_name": "StableBoard",
        "footprint_library": library,
        "board_constraints": _constraints(),
    }
    first_placements = {"U1": (20, 15, 0, "top")}
    first = generate_authoritative_board(
        approved_placements=first_placements,
        placement_approval=_approval(first_placements, "PLA-stable-1"),
        **kwargs,
    )
    first_manifest = json.loads(Path(first.board_manifest_path).read_text(encoding="utf-8"))
    second_placements = {"U1": (21, 15, 0, "top")}
    second = generate_authoritative_board(
        approved_placements=second_placements,
        placement_approval=_approval(second_placements, "PLA-stable-2"),
        **kwargs,
    )
    second_manifest = json.loads(Path(second.board_manifest_path).read_text(encoding="utf-8"))

    assert first_manifest["components"][0]["uuid"] == second_manifest["components"][0]["uuid"]
    assert second_manifest["semantic_changes"] == [{"action": "moved", "reference": "U1"}]


def test_t247_guard_blocks_before_any_authoritative_pad_render_or_file_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def forbidden_render(*_args, **_kwargs):
        pytest.fail("pad renderer must not run before T247 passes")

    monkeypatch.setattr(pcb_handoff, "_render_authoritative_footprint", forbidden_render)
    output = tmp_path / "out"
    placements = {"U1": (20, 15, 0, "top")}
    with pytest.raises(IdentityHandoffBlocked):
        generate_authoritative_board(
            [_component()],
            placements,
            {"U1": _bundle(independent=False)},
            output,
            project_name="BlockedBoard",
            placement_approval=_approval(placements, "PLA-blocked"),
            board_constraints=_constraints(),
            footprint_library=_library(tmp_path / "libs"),
        )

    assert not output.exists()


def test_four_layer_handoff_emits_internal_copper_layers(tmp_path: Path) -> None:
    placements = {"U1": (20, 15, 0, "top")}
    result = generate_authoritative_board(
        [_component()],
        placements,
        {"U1": _bundle()},
        tmp_path / "out",
        project_name="FourLayer",
        placement_approval=_approval(placements, "PLA-four"),
        board_constraints=_constraints(),
        footprint_library=_library(tmp_path / "libs"),
        copper_layers=4,
    )
    board = Path(result.board_path).read_text(encoding="utf-8")
    assert '(4 "In1.Cu" power)' in board
    assert '(6 "In2.Cu" power)' in board


def test_stale_or_mismatched_placement_approval_and_missing_constraints_fail_closed(tmp_path: Path) -> None:
    placements = {"U1": (20, 15, 0, "top")}
    base = {
        "components": [_component()],
        "approved_placements": placements,
        "identity_handoffs": {"U1": _bundle()},
        "output_dir": tmp_path / "out",
        "project_name": "ApprovalGate",
        "footprint_library": _library(tmp_path / "libs"),
    }
    stale = approve_placements(
        placements,
        approval_id="PLA-stale",
        approved_at="2000-01-01T00:00:00Z",
        expires_at="2100-01-01T00:00:00Z",
    )
    stale = pcb_handoff.PlacementApproval(
        stale.id,
        stale.placement_sha256,
        "2000-01-01T00:00:00Z",
        "2001-01-01T00:00:00Z",
    )
    with pytest.raises(pcb_handoff.PcbHandoffError, match="stale"):
        generate_authoritative_board(
            placement_approval=stale,
            board_constraints=_constraints(),
            **base,
        )
    with pytest.raises(pcb_handoff.PcbHandoffError, match="compiled board constraints"):
        generate_authoritative_board(
            placement_approval=_approval(placements),
            board_constraints=(),
            **base,
        )

    assert not (tmp_path / "out").exists()


@pytest.mark.parametrize("copper_layers", [2, 4])
@pytest.mark.skip_category("optional-tool")
def test_authoritative_golden_round_trips_through_kicad_cli(
    tmp_path: Path,
    copper_layers: int,
) -> None:
    cli = os.environ.get("KICAD_CLI") or shutil.which("kicad-cli")
    if not cli:
        pytest.skip("KiCad CLI is not available")
    placements = {"U1": (20, 15, 0, "top")}
    result = generate_authoritative_board(
        [_component()],
        placements,
        {"U1": _bundle()},
        tmp_path / "out",
        project_name=f"Golden{copper_layers}Layer",
        placement_approval=_approval(placements, f"PLA-golden-{copper_layers}"),
        board_constraints=_constraints(),
        footprint_library=_library(tmp_path / "libs"),
        copper_layers=copper_layers,
    )
    load_target = tmp_path / f"load-{copper_layers}.kicad_pcb"
    shutil.copy2(result.board_path, load_target)

    completed = subprocess.run(
        [cli, "pcb", "upgrade", "--force", str(load_target)],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert load_target.stat().st_size > 0
