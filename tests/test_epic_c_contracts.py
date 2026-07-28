"""Frozen Epic C contracts that must land before authoritative board producers."""

from __future__ import annotations

from pathlib import Path

import pytest

from circuit_weaver.component_db import ComponentDef
from circuit_weaver.manufacturing_readiness import (
    ManufacturingReadiness,
    ManufacturingReadinessState,
    ReadinessContractError,
    transition_manufacturing_readiness,
)
from circuit_weaver.pcb_contracts import (
    PREVIEW_BANNER,
    PcbArtifactKind,
    PcbConstraint,
    PcbContractError,
    drc_validation_issue,
    inspect_pcb_artifact,
    require_fresh_authoritative_target,
)
from circuit_weaver.pcb_export import generate_pcb_placement
from circuit_weaver.validator import ValidationIssue


def test_preview_and_authoritative_board_contracts_are_pad_banner_xor(tmp_path: Path) -> None:
    component = ComponentDef(
        mpn="TEST-1",
        source_ref="U1",
        value="TEST-1",
        footprint="Package_SO:SOIC-8_3.9x4.9mm_P1.27mm",
    )
    preview_path, _ = generate_pcb_placement([component], tmp_path, project_name="contract")
    preview = inspect_pcb_artifact(preview_path)

    authoritative_path = tmp_path / "contract.kicad_pcb"
    authoritative_text = """(kicad_pcb (version 20240108) (generator \"circuit-weaver pcb_handoff\")
  (footprint \"Package_SO:SOIC-8_3.9x4.9mm_P1.27mm\" (layer \"F.Cu\")
    (pad \"1\" smd rect (at 0 0) (size 1 1) (layers \"F.Cu\" \"F.Paste\" \"F.Mask\")))
)"""
    authoritative_path.write_text(authoritative_text, encoding="utf-8")
    authoritative = inspect_pcb_artifact(authoritative_path)

    assert preview.kind is PcbArtifactKind.PREVIEW
    assert preview.has_preview_banner and not preview.has_pads
    assert authoritative.kind is PcbArtifactKind.AUTHORITATIVE
    assert authoritative.has_pads and not authoritative.has_preview_banner
    assert preview.has_preview_banner ^ preview.has_pads
    assert authoritative.has_preview_banner ^ authoritative.has_pads


def test_preview_with_pads_and_authoritative_without_pads_fail_closed(tmp_path: Path) -> None:
    with pytest.raises(PcbContractError, match="mutually exclusive"):
        inspect_pcb_artifact(
            tmp_path / "bad_placement_preview.kicad_pcb",
            f'(kicad_pcb (generator "{PREVIEW_BANNER}") (footprint "X:Y" (pad "1" smd rect)))',
        )
    with pytest.raises(PcbContractError, match="requires real footprints and pads"):
        inspect_pcb_artifact(tmp_path / "bad.kicad_pcb", '(kicad_pcb (generator "pcbnew"))')


def test_preview_cannot_be_upgraded_in_place_or_relabeled() -> None:
    preview = Path("out/design_placement_preview.kicad_pcb")
    with pytest.raises(PcbContractError, match="upgraded in place"):
        require_fresh_authoritative_target(preview, preview)
    with pytest.raises(PcbContractError, match="preview filename"):
        require_fresh_authoritative_target(preview, Path("other/design_placement_preview.kicad_pcb"))
    assert require_fresh_authoritative_target(preview, Path("out/design.kicad_pcb")) == Path("out/design.kicad_pcb")


def test_pcb_constraint_id_is_deterministic_unit_labelled_and_evidence_linked() -> None:
    kwargs = {
        "klass": "width",
        "target": "net:VBUS",
        "params": {"minimum": {"value": 0.5, "unit": "mm"}},
        "origin": "calculated",
        "evidence_ids": ("EV-CALCULATION-0123456789ab",),
    }
    first = PcbConstraint.create(**kwargs)
    second = PcbConstraint.create(**kwargs)

    assert first == second
    assert first.id.startswith("PCBC-WIDTH-") and len(first.id.rsplit("-", 1)[1]) == 12
    assert first.to_dict()["origin"] == "calculated"
    with pytest.raises(PcbContractError, match="explicit units"):
        PcbConstraint.create(klass="width", target="net:VBUS", params={"minimum": 0.5}, origin="calculated")


def test_drc_findings_reuse_t248_validation_issue_without_a_fork() -> None:
    issue = drc_validation_issue(
        rule_number=7,
        message="clearance violation",
        severity="blocker",
        evidence_ids=("EV-TOOL_RESULT-0123456789ab",),
        ref="U1",
        net="VBUS",
        observed_value="0.10 mm",
        expected_constraint="clearance at least 0.20 mm",
        safest_next_action="increase copper clearance",
    )

    assert type(issue) is ValidationIssue
    assert issue.rule_id == "CW-DRC-007"
    assert issue.detection_confidence == "verified"


def test_manufacturing_readiness_is_ordered_and_fabrication_ready_is_evidence_gated() -> None:
    current = ManufacturingReadiness()
    current = transition_manufacturing_readiness(current, ManufacturingReadinessState.NEEDS_REVIEW)
    current = transition_manufacturing_readiness(current, ManufacturingReadinessState.DRC_PENDING)
    drc_evidence = {
        "id": "EV-TOOL_RESULT-0123456789ab",
        "subject_ref": "tool:drc",
        "kind": "tool_result",
        "confidence": "verified",
        "conflicts": [],
    }
    current = transition_manufacturing_readiness(
        current,
        ManufacturingReadinessState.DRC_CLEAN,
        evidence_records=(drc_evidence,),
        drc_passed=True,
    )
    assert current.state is ManufacturingReadinessState.DRC_CLEAN

    with pytest.raises(ReadinessContractError, match="T244.4"):
        transition_manufacturing_readiness(current, ManufacturingReadinessState.FABRICATION_READY)
