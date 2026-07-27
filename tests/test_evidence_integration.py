"""End-to-end evidence propagation through validation and generation."""

from __future__ import annotations

import json
from pathlib import Path

from circuit_weaver.dispatcher import generate_artifacts, validate_design
from circuit_weaver.evidence import MANIFEST_SCHEMA_VERSION

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE = REPO_ROOT / "benchmarks" / "electrical" / "negative" / "power" / "design.json"


def _fixture_spec() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_validation_ids_resolve_to_the_embedded_evidence_manifest():
    report = validate_design(_fixture_spec(), check_determinism=False)
    payload = report.to_dict()
    manifest = payload["metadata"]["evidence_manifest"]
    known_ids = {record["id"] for record in manifest["records"]}

    assert manifest["schema_version"] == MANIFEST_SCHEMA_VERSION
    assert payload["evidence_ids"]
    assert set(payload["evidence_ids"]) <= known_ids
    findings = [finding for messages in payload["categories"].values() for finding in messages]
    assert any(finding["code"] == "power-budget" and finding["evidence_ids"] for finding in findings)


def test_generation_publishes_one_portable_evidence_ledger_across_artifacts(tmp_path):
    result = generate_artifacts(
        _fixture_spec(),
        output_dir=tmp_path,
        export_svg=False,
        svg_placement=False,
        require_valid=False,
        readiness_gate=False,
    )

    evidence_path = Path(result["evidence_manifest"])
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    known_ids = {record["id"] for record in evidence["records"]}
    validation = json.loads(Path(result["validation_report"]).read_text(encoding="utf-8"))
    assembly = json.loads(Path(result["assembly_manifest"]).read_text(encoding="utf-8"))
    artifact = json.loads(Path(result["artifact_manifest"]).read_text(encoding="utf-8"))

    assert evidence["schema_version"] == MANIFEST_SCHEMA_VERSION
    assert set(validation["evidence_ids"]) <= known_ids
    assert set(assembly["evidence_ids"]) <= known_ids
    assert any(item["evidence_ids"] for item in assembly["items"] if item["reference"] == "J1")
    assert artifact["evidence_manifest"] == "evidence_manifest.json"
    assert set(artifact["evidence_ids"]) <= known_ids
    assert any(item["path"] == "evidence_manifest.json" for item in artifact["artifacts"])
    assert str(tmp_path.resolve()) not in evidence_path.read_text(encoding="utf-8")

    design_report = next(tmp_path.glob("*_report.md"))
    report_text = design_report.read_text(encoding="utf-8")
    assert "## Evidence Traceability" in report_text
    assert "evidence_manifest.json" in report_text
