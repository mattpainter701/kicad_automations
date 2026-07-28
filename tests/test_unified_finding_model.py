"""T253.1-T253.4 frozen unified-finding contract tests."""

from __future__ import annotations

import json
from dataclasses import replace

import pytest

from circuit_weaver.finding_model import (
    FINDING_SCHEMA_VERSION,
    FindingLocation,
    FindingModelError,
    FindingObservation,
    RemediationOption,
    UnifiedFinding,
    deduplicate_findings,
    finding_from_dict,
    findings_document,
    findings_json,
    findings_sarif,
    findings_sarif_json,
    from_import_analysis,
    from_validation_issue,
)
from circuit_weaver.validator import ValidationIssue

EVIDENCE_A = "EV-TOOL_RESULT-0123456789ab"
EVIDENCE_B = "EV-VALIDATION-abcdef012345"


def _location(*, path: str = "design/main.kicad_sch") -> FindingLocation:
    return FindingLocation(
        artifact_kind="schematic",
        artifact_path=path,
        object_type="component",
        object_id="U1",
        ref="U1",
        sheet="/power",
    )


def _finding(
    *,
    source: str = "validator",
    severity: str = "major",
    confidence: str = "verified",
    evidence_ids: tuple[str, ...] = (EVIDENCE_A,),
    verification_status: str = "unverified",
    path: str = "design/main.kicad_sch",
) -> UnifiedFinding:
    location = _location(path=path)
    observation = FindingObservation(
        source=source,
        source_finding_id="power-over-voltage",
        message="U1 input exceeds the absolute maximum",
        severity=severity,
        detection_confidence=confidence,
        location=location,
        evidence_ids=evidence_ids,
        observed_value="6.0 V",
    )
    return UnifiedFinding(
        rule_id="CW-PWR-001",
        root_cause_key="power-over-voltage|U1|VIN",
        message=observation.message,
        severity=severity,
        detection_confidence=confidence,
        location=location,
        observations=(observation,),
        evidence_ids=evidence_ids,
        remediation_options=(
            RemediationOption(
                id="REM-lower-vin",
                summary="Lower VIN or choose a correctly rated regulator.",
            ),
        ),
        verification_status=verification_status,
    )


def test_finding_identity_is_deterministic_and_schema_versioned() -> None:
    first = _finding()
    second = _finding(evidence_ids=(EVIDENCE_B, EVIDENCE_A))

    assert first.id == second.id
    assert first.id.startswith("FND-")
    assert first.to_dict()["schema_version"] == FINDING_SCHEMA_VERSION
    assert first.to_dict()["location"]["artifact_path"] == "design/main.kicad_sch"
    assert first.to_dict()["verification_status"] == "unverified"
    assert first.to_dict()["remediation_options"][0]["supported"] is False


@pytest.mark.parametrize(
    ("factory", "message"),
    [
        (lambda: _location(path="C:/users/ci/board.kicad_pcb"), "project-relative"),
        (lambda: _location(path="../board.kicad_pcb"), "project-relative"),
        (
            lambda: replace(_finding(), verification_status="passed"),
            "verification_status",
        ),
        (
            lambda: FindingLocation(artifact_kind="pcb"),
            "exact object",
        ),
    ],
)
def test_frozen_schema_rejects_unsafe_or_unknown_values(factory, message: str) -> None:
    with pytest.raises(FindingModelError, match=message):
        factory()


def test_deduplication_retains_observations_without_confidence_promotion() -> None:
    verified = _finding(source="validator", severity="major", confidence="verified")
    heuristic = _finding(
        source="import.pcb",
        severity="blocker",
        confidence="heuristic",
        evidence_ids=(EVIDENCE_B,),
        path="imported/main.kicad_sch",
    )

    merged = deduplicate_findings((heuristic, verified))

    assert len(merged) == 1
    finding = merged[0]
    assert finding.id == verified.id == heuristic.id
    assert finding.severity == "blocker"
    assert finding.detection_confidence == "heuristic"
    assert finding.evidence_ids == (EVIDENCE_A, EVIDENCE_B)
    assert [item.source for item in finding.observations] == ["import.pcb", "validator"]
    assert {item.location.artifact_path for item in finding.observations} == {
        "design/main.kicad_sch",
        "imported/main.kicad_sch",
    }


def test_validation_issue_adapter_preserves_t248_axes_and_suppression() -> None:
    issue = ValidationIssue(
        code="power-over-voltage",
        ref="U1",
        message="U1 input exceeds the absolute maximum",
        suggestion="Lower VIN.",
        severity="blocker",
        detection_confidence="corroborated",
        rule_id="CW-PWR-001",
        observed_value="6.0 V",
        expected_constraint="<= 5.5 V",
        evidence_ids=(EVIDENCE_A,),
        safest_next_action="Lower VIN.",
        suppressed=True,
        suppression_id="SUP-u1-vin",
        net="VIN",
    )

    finding = from_validation_issue(
        issue,
        source="validator",
        artifact_kind="schematic",
        artifact_path="main.kicad_sch",
    )

    assert finding.rule_id == "CW-PWR-001"
    assert finding.severity == "blocker"
    assert finding.detection_confidence == "corroborated"
    assert finding.location.ref == "U1"
    assert finding.location.net == "VIN"
    assert finding.evidence_ids == (EVIDENCE_A,)
    assert finding.suppressed is True
    assert finding.suppression_id == "SUP-u1-vin"
    assert finding.remediation_options[0].summary == "Lower VIN."


def test_json_round_trip_is_strict_and_tamper_evident() -> None:
    finding = _finding()
    document = findings_document((finding, finding))

    assert document["finding_count"] == 1
    assert json.loads(findings_json((finding,))) == document
    loaded = finding_from_dict(document["findings"][0])
    assert loaded == finding

    tampered = dict(document["findings"][0])
    tampered["root_cause_key"] = "different-root-cause"
    with pytest.raises(FindingModelError, match="id does not match"):
        finding_from_dict(tampered)


def test_sarif_retains_finding_identity_trust_axes_and_remediation() -> None:
    finding = _finding(severity="blocker", confidence="corroborated")
    sarif = findings_sarif((finding,))
    result = sarif["runs"][0]["results"][0]

    assert sarif["version"] == "2.1.0"
    assert result["ruleId"] == "CW-PWR-001"
    assert result["level"] == "error"
    assert result["partialFingerprints"]["circuitWeaverFindingId/v1"] == finding.id
    assert result["locations"][0]["physicalLocation"]["artifactLocation"] == {
        "uri": "design/main.kicad_sch",
        "uriBaseId": "%SRCROOT%",
    }
    assert result["properties"]["detection_confidence"] == "corroborated"
    assert result["properties"]["verification_status"] == "unverified"
    assert result["properties"]["evidence_ids"] == [EVIDENCE_A]
    assert result["properties"]["remediation_options"][0]["id"] == "REM-lower-vin"
    assert json.loads(findings_sarif_json((finding,))) == sarif


def test_missing_rule_id_never_crosses_normalization_boundary() -> None:
    issue = ValidationIssue(
        code="legacy-unmapped",
        ref="U1",
        message="Legacy analyzer output",
        severity="major",
        detection_confidence="single_source",
    )

    with pytest.raises(FindingModelError, match="stable rule_id"):
        from_validation_issue(issue, source="validator", artifact_kind="schematic")


def test_imported_pcb_dfm_uses_registered_rules_and_preserves_trust() -> None:
    findings = from_import_analysis(
        "pcb",
        {
            "dfm": {
                "violations": [
                    {
                        "parameter": "track_width",
                        "actual_mm": 0.08,
                        "tier_required": "challenging",
                        "message": "Minimum track width is 0.08 mm",
                    },
                    {
                        "parameter": "track_spacing",
                        "actual_mm": 0.09,
                        "tier_required": "standard",
                        "message": "Estimated spacing is 0.09 mm",
                    },
                    {"parameter": "future_unregistered_check", "actual_mm": 0.1},
                ]
            }
        },
        artifact_path="imports/controller.kicad_pcb",
    )

    assert [finding.rule_id for finding in findings] == ["CW-DFM-001", "CW-DFM-002"]
    by_rule = {finding.rule_id: finding for finding in findings}
    assert by_rule["CW-DFM-001"].severity == "major"
    assert by_rule["CW-DFM-001"].detection_confidence == "single_source"
    assert by_rule["CW-DFM-001"].observations[0].observed_value == "0.08 mm"
    assert by_rule["CW-DFM-002"].detection_confidence == "heuristic"
    assert all(finding.location.artifact_path == "imports/controller.kicad_pcb" for finding in findings)
    assert all(not finding.remediation_options[0].supported for finding in findings)


def test_imported_gerber_alignment_deduplicates_but_retains_observations() -> None:
    findings = from_import_analysis(
        "gerbers",
        {
            "alignment": {
                "method": "conflicting_x2_metadata",
                "issues": ["Copper and drill origins differ", "X2 metadata conflicts"],
            }
        },
        artifact_path="fabrication/rev-a",
    )

    assert len(findings) == 1
    finding = findings[0]
    assert finding.rule_id == "CW-DFM-007"
    assert finding.detection_confidence == "conflicting"
    assert len(finding.observations) == 2
    assert {item.message for item in finding.observations} == {
        "Copper and drill origins differ",
        "X2 metadata conflicts",
    }


def test_import_adapter_rejects_unknown_producers_without_guessing() -> None:
    assert from_import_analysis("schematic", {}, artifact_path="main.kicad_sch") == ()
    with pytest.raises(FindingModelError, match="unsupported import analyzer kind"):
        from_import_analysis("bom", {}, artifact_path="bom.json")
