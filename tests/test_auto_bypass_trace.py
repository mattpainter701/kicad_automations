"""Traceability contracts for automatic bypass synthesis."""

import pytest

from circuit_weaver import calc
from circuit_weaver.component_db import (
    ComponentDef,
    PassiveRecommendation,
    auto_generate_bypass_caps,
    emit_and_retain_passive_synthesis,
)
from circuit_weaver.dispatcher import ValidationReport
from circuit_weaver.evidence import EvidenceLedger, build_validation_evidence


def _component(*recommendations: PassiveRecommendation) -> ComponentDef:
    return ComponentDef(
        mpn="TRACE_IC",
        ref_prefix="U",
        source_ref="U1",
        power_pins={"1": "VIN", "2": "GND"},
        passive_recommendations=list(recommendations),
    )


def _recommendation(policy: str, value: float, **extra: object) -> PassiveRecommendation:
    payload: dict[str, object] = {
        "family": "regulator_io_cap",
        "role": "decoupling",
        "precedence_policy": policy,
        "confidence": "heuristic" if policy == "bounded_fallback" else "single_source",
        "provenance": "https://example.test/trace-ic.pdf",
        "value": value,
        "unit": "F",
        "net": "VIN",
    }
    payload.update(extra)
    return PassiveRecommendation(**payload)


def _three_rail_component(*recommendations: PassiveRecommendation) -> ComponentDef:
    return ComponentDef(
        mpn="TRACE_THREE_RAIL",
        ref_prefix="U",
        source_ref="U3",
        power_pins={"1": "VIN", "2": "VDD_3P3", "3": "VDD_1P8", "4": "GND"},
        passive_recommendations=list(recommendations),
    )


def test_datasheet_recommendation_wins_and_emits_real_traceability() -> None:
    component = _component(_recommendation("datasheet", 1e-6))

    assert auto_generate_bypass_caps([component]) == 1
    cap = component.bypass_caps[0]
    assert cap.value == "1uF"
    assert cap.selection_policy == "datasheet"
    assert cap.calculation_id and cap.evidence_ids
    assert {record.kind for record in component.passive_synthesis_evidence} == {"datasheet", "calculation"}


def test_builtin_fallback_is_heuristic_and_never_silent() -> None:
    component = _component()

    assert auto_generate_bypass_caps([component]) == 1
    cap = component.bypass_caps[0]
    assert cap.selection_policy == "bounded_fallback"
    assert cap.confidence == "heuristic"
    assert cap.calculation_id and cap.evidence_ids


def test_conflict_and_out_of_range_recommendations_are_withheld() -> None:
    conflict = _component(_recommendation("datasheet", 1e-6), _recommendation("datasheet", 2.2e-6))
    out_of_range = _component(_recommendation("datasheet", 10e-6, fallback_min=100e-9, fallback_max=1e-6))

    assert auto_generate_bypass_caps([conflict]) == 0
    assert auto_generate_bypass_caps([out_of_range]) == 0
    assert not conflict.bypass_caps and conflict.passive_synthesis_findings
    assert not out_of_range.bypass_caps and out_of_range.passive_synthesis_findings


def test_synthesis_records_have_no_dangling_evidence_and_roundtrip_manifest() -> None:
    component = _component(_recommendation("datasheet", 1e-6))
    auto_generate_bypass_caps([component])

    report = ValidationReport(profile="standard", valid=True)
    ledger, evidence_by_ref = build_validation_evidence([component], report)
    manifest = ledger.to_manifest()
    restored = EvidenceLedger.from_manifest(manifest)
    known = {record["id"] for record in manifest["records"]}

    assert set(component.bypass_caps[0].evidence_ids) <= known
    assert set(component.bypass_caps[0].evidence_ids) <= set(evidence_by_ref["U1"])
    assert restored.to_manifest() == manifest


def test_datasheet_bulk_recommendation_beats_builtin_heuristic_without_duplicates() -> None:
    component = _three_rail_component(_recommendation("datasheet", 22e-6, role="bulk", net="VDD_3P3"))

    assert auto_generate_bypass_caps([component]) == 1
    bulk = [cap for cap in component.bypass_caps if cap.value == "22uF"]
    assert len(bulk) == 1 and bulk[0].selection_policy == "datasheet"
    assert not [cap for cap in component.bypass_caps if cap.value == "10uF"]
    assert auto_generate_bypass_caps([component]) == 0
    assert len([cap for cap in component.bypass_caps if cap.value == "22uF"]) == 1


def test_bulk_conflict_withholds_only_bulk_while_rail_caps_remain() -> None:
    component = _three_rail_component(
        _recommendation("datasheet", 10e-6, role="bulk", net="VDD_3P3"),
        _recommendation("datasheet", 22e-6, role="bulk", net="VDD_3P3"),
    )

    assert auto_generate_bypass_caps([component]) == 1
    assert len([cap for cap in component.bypass_caps if cap.value == "100nF"]) == 3
    assert not [cap for cap in component.bypass_caps if cap.value in {"10uF", "22uF"}]
    assert component.passive_synthesis_findings


def test_bulk_fallback_is_explicitly_traced() -> None:
    component = _three_rail_component()

    auto_generate_bypass_caps([component])
    bulk = [cap for cap in component.bypass_caps if cap.value == "10uF"]
    assert len(bulk) == 1
    assert bulk[0].selection_policy == "bounded_fallback"
    assert bulk[0].evidence_ids


def test_shared_producer_adapter_emits_and_retains_calculation_evidence() -> None:
    component = _component()
    decision = calc.bounded_fallback_scalar(
        target="param:U1.interface.termination",
        value=120.0,
        minimum=100.0,
        maximum=130.0,
        unit="ohm",
        series="E24",
    )

    emitted = emit_and_retain_passive_synthesis(component, decision.calculation)

    assert emitted.emits_evidence
    assert component.passive_synthesis_calculations == [emitted]
    assert {record.id for record in component.passive_synthesis_evidence} == {emitted.emits_evidence}


def test_shared_producer_adapter_rejects_missing_datasheet_evidence() -> None:
    component = _component()
    calculation = calc.datasheet_selected_scalar(
        target="param:U1.interface.termination",
        value=120.0,
        unit="ohm",
        evidence_id="EV-DATASHEET-aaaaaaaaaaaa",
    )

    with pytest.raises(ValueError, match="does not resolve"):
        emit_and_retain_passive_synthesis(component, calculation)
