"""T248.2 contract tests for independent validation severity and confidence."""

from __future__ import annotations

import pytest

from circuit_weaver.validator import ValidationIssue


def test_confirmed_blocker_renders_as_legacy_error():
    issue = ValidationIssue(
        "CW-ID-001",
        ref="U1",
        message="Exact identity disagrees with selected footprint",
        severity="blocker",
        detection_confidence="corroborated",
    )

    assert issue.level == "error"
    assert issue.is_confirmed_blocker
    assert issue.to_dict()["level"] == "error"
    assert issue.to_dict()["severity"] == "blocker"
    assert issue.to_dict()["detection_confidence"] == "corroborated"


def test_weak_blocker_renders_as_review_item_not_confirmed_error():
    issue = ValidationIssue(
        "CW-PSV-001",
        ref="U1",
        message="Passive selection has insufficient basis",
        severity="blocker",
        detection_confidence="heuristic",
    )

    assert issue.level == "warning"
    assert not issue.is_confirmed_blocker
    assert issue.to_dict()["confirmed_blocker"] is False


def test_legacy_positional_construction_remains_compatible():
    issue = ValidationIssue("legacy", "error", "U1", "MPN", "message", "fix")

    assert issue.severity == "blocker"
    assert issue.detection_confidence == "verified"
    assert issue.level == "error"
    assert issue.suggestion == "fix"


@pytest.mark.parametrize(
    ("kwargs", "match"),
    [
        ({"severity": "critical"}, "severity"),
        ({"detection_confidence": "likely"}, "detection confidence"),
    ],
)
def test_schema_rejects_values_outside_frozen_ladders(kwargs: dict[str, str], match: str):
    with pytest.raises(ValueError, match=match):
        ValidationIssue("bad", message="bad", **kwargs)
