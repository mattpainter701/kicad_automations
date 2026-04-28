"""Dedicated tests for circuit_weaver.placement_readiness."""

from __future__ import annotations

import pytest

from circuit_weaver.component_db import BypassCap, ComponentDef, StrapConfig
from circuit_weaver.design_ir import DesignBlock, DesignInterface, DesignIR
from circuit_weaver.placement_readiness import (
    PlacementReadinessReport,
    categorize_for_placement,
    placement_readiness_issues,
)
from circuit_weaver.validator import ValidationCheckResult, ValidationIssue

PROMOTED_CODES = [
    "single-pin-net",
    "undriven-net",
    "i2c-missing-pullup",
    "spi-floating-cs",
    "uart-unpaired",
    "floating-enable",
    "floating-power-pin",
    "unverified-pinout",
    "vdd-to-gnd-short",
]


def _issue(code: str, suggestion: str = "") -> ValidationIssue:
    return ValidationIssue(
        code=code,
        level="warning",
        ref="U1",
        mpn="TEST",
        message=f"{code} message",
        suggestion=suggestion,
    )


def _result(result_code: str, *issues: ValidationIssue) -> ValidationCheckResult:
    return ValidationCheckResult(
        code=result_code,
        label=result_code,
        status="warning" if issues else "pass",
        issues=tuple(issues),
    )


def _ir(*interfaces: tuple[str, str, str]) -> DesignIR:
    blocks = []
    for ref, net, direction in interfaces:
        blocks.append(
            DesignBlock(
                id=f"block:{ref}",
                section="test",
                kind="component",
                ref=ref,
                interfaces=[DesignInterface(block_id=f"block:{ref}", name=net, direction=direction)],
            )
        )
    return DesignIR(blocks=blocks)


def _comp(ref: str, **kwargs) -> ComponentDef:
    return ComponentDef(mpn=ref, source_ref=ref, **kwargs)


@pytest.mark.parametrize("code", PROMOTED_CODES)
def test_categorize_for_placement_promotes_blocking_codes(code):
    assert categorize_for_placement(code) is True


def test_categorize_for_placement_ignores_soft_electrical_code():
    assert categorize_for_placement("decoupling") is False


def test_promotes_result_level_code_to_error_with_fallback_suggestion():
    out = placement_readiness_issues(
        [_result("single-pin-net", _issue("single-pin-net"))],
        _ir(),
        [],
    )

    assert len(out) == 1
    assert out[0].code == "single-pin-net"
    assert out[0].level == "error"
    assert "dangling" in out[0].suggestion.lower()


def test_promotes_issue_level_code_from_fanout_result():
    out = placement_readiness_issues(
        [_result("bus-completeness", _issue("i2c-missing-pullup"))],
        _ir(),
        [],
    )

    assert [issue.code for issue in out] == ["i2c-missing-pullup"]
    assert out[0].level == "error"


def test_preserves_existing_validator_suggestion():
    out = placement_readiness_issues(
        [_result("single-pin-net", _issue("single-pin-net", suggestion="Wire TP1 to J1"))],
        _ir(),
        [],
    )

    assert out[0].suggestion == "Wire TP1 to J1"


def test_ignores_non_promoted_validator_issue():
    out = placement_readiness_issues(
        [_result("decoupling", _issue("decoupling"))],
        _ir(),
        [],
    )

    assert out == []


def test_orphan_interface_detected_when_no_other_block_uses_net():
    out = placement_readiness_issues([], _ir(("U1", "SENSOR_IRQ", "output")), [_comp("U1")])

    assert len(out) == 1
    assert out[0].code == "orphan-interface"
    assert out[0].level == "error"
    assert "SENSOR_IRQ" in out[0].message


def test_orphan_interface_ignored_when_other_block_uses_pin_net():
    out = placement_readiness_issues(
        [],
        _ir(("U1", "I2C_SDA", "bidirectional")),
        [_comp("U1", pin_nets={"1": "I2C_SDA"}), _comp("U2", pin_nets={"2": "I2C_SDA"})],
    )

    assert out == []


def test_orphan_interface_ignored_when_other_block_uses_power_pin():
    out = placement_readiness_issues(
        [],
        _ir(("U1", "VREF", "output")),
        [_comp("U1", power_pins={"1": "VREF"}), _comp("U2", power_pins={"2": "VREF"})],
    )

    assert out == []


def test_orphan_interface_ignored_when_other_block_uses_bypass_cap_net():
    out = placement_readiness_issues(
        [],
        _ir(("U1", "ANALOG_BIAS", "output")),
        [
            _comp("U1", pin_nets={"1": "ANALOG_BIAS"}),
            _comp("U2", bypass_caps=[BypassCap("1", "ANALOG_BIAS", "GND", "100nF", "C_0402")]),
        ],
    )

    assert out == []


def test_orphan_interface_ignored_when_other_block_uses_strap_net_or_rail():
    out = placement_readiness_issues(
        [],
        _ir(("U1", "BOOT", "bidirectional"), ("U3", "PULL_RAIL", "output")),
        [
            _comp("U1", pin_nets={"1": "BOOT"}),
            _comp("U2", straps=[StrapConfig("2", "BOOT", "PULL_RAIL", "10k", "R_0402")]),
            _comp("U3", pin_nets={"3": "PULL_RAIL"}),
        ],
    )

    assert out == []


def test_orphan_interface_excludes_power_and_ground_nets():
    out = placement_readiness_issues(
        [],
        _ir(("U1", "VDD_3P3", "output"), ("U2", "GND", "passive")),
        [_comp("U1"), _comp("U2")],
    )

    assert out == []


def test_empty_interface_name_is_ignored():
    out = placement_readiness_issues([], _ir(("U1", "", "output")), [_comp("U1")])

    assert out == []


def test_self_connection_only_still_counts_as_orphan():
    out = placement_readiness_issues(
        [],
        _ir(("U1", "SELF_ONLY", "output")),
        [_comp("U1", pin_nets={"1": "SELF_ONLY"})],
    )

    assert len(out) == 1
    assert out[0].code == "orphan-interface"


def test_placement_readiness_report_to_dict_copies_payload():
    report = PlacementReadinessReport(
        ready=False,
        blocking=[{"code": "single-pin-net"}],
        auto_repaired=[{"kind": "i2c_pullups"}],
        summary={"errors": 1},
    )

    payload = report.to_dict()
    payload["blocking"].append({"code": "extra"})
    payload["summary"]["errors"] = 99

    assert report.blocking == [{"code": "single-pin-net"}]
    assert report.summary == {"errors": 1}


def test_multiple_promoted_results_preserve_order():
    out = placement_readiness_issues(
        [
            _result("single-pin-net", _issue("single-pin-net")),
            _result("enable-pins", _issue("floating-enable")),
        ],
        _ir(),
        [],
    )

    assert [issue.code for issue in out] == ["single-pin-net", "floating-enable"]
