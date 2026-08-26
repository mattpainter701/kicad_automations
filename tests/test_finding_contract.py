"""T248.3/.4 release-grade finding and suppression contract tests."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from circuit_weaver.finding_contract import (
    SUPPRESSION_SCHEMA_VERSION,
    FindingContractError,
    Suppression,
    apply_suppressions,
    finding_contract_violations,
    load_suppressions,
    require_finding_contract,
    validate_suppression,
)
from circuit_weaver.validator import ValidationIssue

EVIDENCE_ID = "EV-TOOL_RESULT-0123456789ab"
NOW = datetime(2026, 7, 27, tzinfo=timezone.utc)


def _complete_issue(**overrides: object) -> ValidationIssue:
    values: dict[str, object] = {
        "code": "CW-PWR-001",
        "ref": "U1",
        "message": "Input rail exceeds the allowed voltage",
        "severity": "major",
        "detection_confidence": "verified",
        "observed_value": "6.0 V",
        "expected_constraint": "<= 5.5 V absolute maximum",
        "evidence_ids": (EVIDENCE_ID,),
        "safest_next_action": "Lower VIN or choose a regulator rated for the rail.",
    }
    values.update(overrides)
    return ValidationIssue(**values)  # type: ignore[arg-type]


def test_complete_actionable_finding_has_no_contract_violations() -> None:
    issue = _complete_issue()

    assert finding_contract_violations(issue, known_evidence_ids=(EVIDENCE_ID,)) == ()
    require_finding_contract((issue,), known_evidence_ids=(EVIDENCE_ID,))


@pytest.mark.parametrize(
    ("override", "message"),
    [
        ({"code": "power-over-voltage"}, "rule_id"),
        ({"observed_value": "6.0"}, "unit-labelled"),
        ({"expected_constraint": ""}, "expected_constraint"),
        ({"evidence_ids": ()}, "evidence_ids are required"),
        ({"evidence_ids": ("EV-TOOL_RESULT-deadbeefcafe",)}, "resolve"),
        ({"safest_next_action": ""}, "safest_next_action"),
    ],
)
def test_actionable_finding_omissions_fail_release_contract(override: dict[str, object], message: str) -> None:
    issue = _complete_issue(**override)

    assert message in " ".join(finding_contract_violations(issue, known_evidence_ids=(EVIDENCE_ID,)))
    with pytest.raises(FindingContractError, match=message):
        require_finding_contract((issue,), known_evidence_ids=(EVIDENCE_ID,))


def test_weak_blocker_never_renders_as_confirmed() -> None:
    issue = _complete_issue(severity="blocker", detection_confidence="heuristic")

    assert not issue.is_confirmed_blocker
    assert issue.to_dict()["confirmed_blocker"] is False


@pytest.mark.parametrize(
    ("override", "message"),
    [
        ({"expires_at": ""}, "expires_at"),
        ({"expires_at": "2026-07-26T00:00:00Z"}, "expired"),
        ({"scope": {"ref": "U*"}}, "wildcards"),
        ({"scope": {"ref": "U1", "net": "VIN"}}, "exactly one"),
        ({"approved_by": ""}, "approved_by"),
    ],
)
def test_invalid_suppressions_fail_release_gate(override: dict[str, object], message: str) -> None:
    values: dict[str, object] = {
        "id": "SUP-u1-vin",
        "rule_id": "CW-PWR-001",
        "scope": {"ref": "U1"},
        "owner": "power-owner",
        "reason": "Lab-only input source is bounded externally.",
        "created_at": "2026-07-01T00:00:00Z",
        "expires_at": "2026-08-01T00:00:00Z",
        "approved_by": "reviewer",
    }
    values.update(override)
    with pytest.raises(FindingContractError, match=message):
        validate_suppression(Suppression(**values), now=NOW)  # type: ignore[arg-type]


def test_suppression_marks_but_never_removes_a_finding() -> None:
    issue = _complete_issue()
    suppression = Suppression(
        id="SUP-u1-vin",
        rule_id="CW-PWR-001",
        scope={"ref": "U1"},
        owner="power-owner",
        reason="Lab-only input source is bounded externally.",
        created_at="2026-07-01T00:00:00Z",
        expires_at="2026-08-01T00:00:00Z",
        approved_by="reviewer",
    )

    output = apply_suppressions((issue,), (suppression,), now=NOW)

    assert len(output) == 1
    assert output[0].suppressed is True
    assert output[0].suppression_id == "SUP-u1-vin"
    assert output[0].code == issue.code


def test_empty_versioned_suppression_artifact_loads(tmp_path) -> None:
    path = tmp_path / "suppressions.json"
    path.write_text(json.dumps({"schema_version": SUPPRESSION_SCHEMA_VERSION, "suppressions": []}), encoding="utf-8")

    assert load_suppressions(path, now=NOW) == ()


def test_checked_in_suppression_artifact_is_valid() -> None:
    artifact = Path(__file__).parents[1] / "benchmarks" / "electrical" / "suppressions.json"

    assert load_suppressions(artifact, now=NOW) == ()


def test_validator_release_report_has_resolvable_contract_evidence() -> None:
    """The released report, not a raw pre-ledger object, is the T248 surface."""

    from circuit_weaver.dispatcher import validate_design

    fixture = Path(__file__).parents[1] / "benchmarks" / "electrical" / "negative" / "i2c" / "design.json"
    report = validate_design(json.loads(fixture.read_text(encoding="utf-8")), check_determinism=False)
    ledger_ids = {record["id"] for record in report.metadata["evidence_manifest"]["records"]}
    findings = [
        message for messages in report.categories.values() for message in messages if message.is_validator_finding
    ]

    assert findings
    assert report.metadata["validator_finding_contract"] == "passed"
    assert all(finding_contract_violations(item, known_evidence_ids=ledger_ids) == () for item in findings)


def test_raw_validator_results_carry_resolvable_evidence() -> None:
    from circuit_weaver.component_db import ComponentDef, PinDef
    from circuit_weaver.validator import run_validation_checks

    component = ComponentDef(
        mpn="TEST_STUB",
        ref_prefix="U",
        source_ref="U1",
        pinout_source="stub",
        pins=[PinDef("1", "IN", "input", "L")],
    )
    result = next(item for item in run_validation_checks([component]) if item.code == "pinout-source")
    issue = next(item for item in result.issues if item.code == "unverified-pinout")
    known_ids = {record.id for record in result.evidence_records}

    assert issue.evidence_ids
    assert finding_contract_violations(issue, known_evidence_ids=known_ids) == ()


def test_every_registered_validator_check_is_exercised_or_explicitly_unsupported() -> None:
    """Registry coverage cannot regress into an implicit, untested check."""

    from circuit_weaver.validator import _VALIDATION_CHECK_CONTRACT_COVERAGE, _VALIDATION_CHECKS

    registered = {code for code, _label, _check in _VALIDATION_CHECKS}
    assert set(_VALIDATION_CHECK_CONTRACT_COVERAGE) == registered
    for code, coverage in _VALIDATION_CHECK_CONTRACT_COVERAGE.items():
        assert coverage["status"] in {"adverse_fixture", "unsupported"}, code
        if coverage["status"] == "adverse_fixture":
            fixture = Path(__file__).parents[1] / "benchmarks" / "electrical" / f"{coverage['fixture']}"
            assert (fixture / "design.json").is_file(), code
        else:
            assert isinstance(coverage.get("reason"), str) and coverage["reason"], code
