"""Normalized passive recommendations and feedback-Vref metadata contracts."""

from dataclasses import replace

import pytest

from circuit_weaver.component_db import BypassCap, ComponentDef, PassiveRecommendation, StrapConfig
from circuit_weaver.validator import _validate_feedback_dividers


def _feedback_component(*, vref: float | None) -> ComponentDef:
    return ComponentDef(
        mpn="CUSTOM_REGULATOR",
        ref_prefix="U",
        source_ref="U9",
        feedback_vref_voltage=vref,
        feedback_vref_provenance="https://example.test/custom-regulator.pdf" if vref else None,
        straps=[
            StrapConfig("1", "FB_U9", "GND", "10k", "Resistor_SMD:R_0402_1005Metric"),
            StrapConfig("2", "FB_U9", "VDD_3P3", "10k", "Resistor_SMD:R_0402_1005Metric"),
        ],
    )


def test_feedback_validator_uses_component_metadata_for_custom_parts() -> None:
    issues = _validate_feedback_dividers([_feedback_component(vref=1.0)])

    assert len(issues) == 1
    assert issues[0].code == "feedback-divider"


def test_feedback_validator_skips_unknown_vref_without_mpn_lookup() -> None:
    assert _validate_feedback_dividers([_feedback_component(vref=None)]) == []


def test_legacy_recommended_bypass_normalizes_to_typed_primary_contract() -> None:
    component = ComponentDef(
        mpn="CUSTOM_REGULATOR",
        recommended_bypass=[{"net": "VIN", "value": "1uF", "count": 2}],
        datasheet_url="https://example.test/custom-regulator.pdf",
    )

    recommendation = component.passive_recommendations[0]
    assert recommendation.family == "regulator_io_cap"
    assert recommendation.value == pytest.approx(1e-6)
    assert recommendation.unit == "F"
    assert recommendation.precedence_policy == "datasheet"
    assert recommendation.provenance == component.datasheet_url


@pytest.mark.parametrize(
    "kwargs",
    [
        {
            "precedence_policy": "datasheet",
            "confidence": "single_source",
            "value": 100e-9,
            "unit": "F",
            "min_value": 10e-9,
            "max_value": 1e-6,
        },
        {
            "precedence_policy": "bounded_fallback",
            "confidence": "single_source",
            "min_value": 1e-9,
            "max_value": 100e-9,
            "unit": "F",
            "fallback_min": 1e-9,
            "fallback_max": 100e-9,
        },
        {
            "precedence_policy": "bounded_fallback",
            "confidence": "heuristic",
            "value": 100e-9,
            "unit": "F",
        },
    ],
)
def test_recommendation_precedence_and_bounds_reject_malformed_data(kwargs: dict) -> None:
    with pytest.raises(ValueError):
        PassiveRecommendation(
            family="regulator_io_cap",
            role="decoupling",
            provenance="https://example.test/datasheet.pdf",
            **kwargs,
        )


@pytest.mark.parametrize(
    "overrides",
    [
        {"value": float("nan")},
        {"value": float("inf")},
        {"evidence_id": "not-an-evidence-id"},
        {"provenance": "file:///C:/private/datasheet.pdf"},
        {"unit": "ohm"},
    ],
)
def test_recommendation_rejects_unsafe_or_nonfinite_authority_data(overrides: dict) -> None:
    payload = {
        "family": "regulator_io_cap",
        "role": "decoupling",
        "precedence_policy": "datasheet",
        "confidence": "single_source",
        "provenance": "https://example.test/datasheet.pdf",
        "value": 100e-9,
        "unit": "F",
    }
    payload.update(overrides)

    with pytest.raises(ValueError):
        PassiveRecommendation(**payload)


def test_legacy_datasheet_recommendation_without_source_fails_closed() -> None:
    with pytest.raises(ValueError, match="datasheet recommendations require source"):
        ComponentDef(mpn="UNSOURCED", recommended_bypass=[{"net": "VIN", "value": "1uF"}])


def test_equation_recommendation_requires_calculation_evidence_id() -> None:
    with pytest.raises(ValueError, match="calculation evidence_id"):
        PassiveRecommendation(
            family="regulator_io_cap",
            role="decoupling",
            precedence_policy="equation",
            confidence="single_source",
            provenance="https://example.test/equation.pdf",
            evidence_id="EV-DATASHEET-abcdefabcdef",
            value=100e-9,
            unit="F",
        )


def test_emitted_passive_traceability_is_complete_and_uses_frozen_ids() -> None:
    with pytest.raises(ValueError, match="calculation_id is malformed"):
        BypassCap("1", "VDD", "GND", "100nF", "C_0402", calculation_id="not-a-calculation")
    with pytest.raises(ValueError, match="requires policy, confidence, and calculation_id"):
        BypassCap("1", "VDD", "GND", "100nF", "C_0402", selection_policy="datasheet")
    with pytest.raises(ValueError, match="must remain heuristic"):
        BypassCap(
            "1",
            "VDD",
            "GND",
            "100nF",
            "C_0402",
            selection_policy="bounded_fallback",
            confidence="single_source",
            calculation_id="CALC-BOUNDED_FALLBACK-0123456789ab",
            evidence_ids=("EV-CALCULATION-0123456789ab",),
        )
    traced = BypassCap(
        "1",
        "VDD",
        "GND",
        "100nF",
        "C_0402",
        selection_policy="bounded_fallback",
        confidence="heuristic",
        calculation_id="CALC-BOUNDED_FALLBACK-0123456789ab",
        evidence_ids=("EV-CALCULATION-0123456789ab",),
    )
    assert traced.eligibility == "eligible"


def _recommendation(
    policy: str, value: float, *, net: str | None = None, fallback_bounds: tuple[float, float] | None = None
) -> PassiveRecommendation:
    payload = {
        "family": "regulator_io_cap",
        "role": "decoupling",
        "precedence_policy": policy,
        "confidence": "heuristic" if policy == "bounded_fallback" else "single_source",
        "provenance": "https://example.test/recommendation.pdf",
        "value": value,
        "unit": "F",
        "net": net,
    }
    if policy == "equation":
        payload["evidence_id"] = "EV-CALCULATION-abcdefabcdef"
    if fallback_bounds is not None:
        payload["fallback_min"], payload["fallback_max"] = fallback_bounds
    return PassiveRecommendation(**payload)


def test_recommendation_selector_uses_exact_precedence_deterministically() -> None:
    component = ComponentDef(
        mpn="SELECTOR",
        passive_recommendations=[
            _recommendation("bounded_fallback", 1e-6, fallback_bounds=(100e-9, 10e-6)),
            _recommendation("equation", 2.2e-6),
            _recommendation("datasheet", 4.7e-6),
        ],
    )

    first = component.select_passive_recommendation("regulator_io_cap", "decoupling")
    second = ComponentDef(
        mpn="SELECTOR_REVERSED", passive_recommendations=list(reversed(component.passive_recommendations))
    ).select_passive_recommendation("regulator_io_cap", "decoupling")

    assert first.outcome == second.outcome == "selected"
    assert first.recommendation is not None
    assert first.recommendation.value == second.recommendation.value == pytest.approx(4.7e-6)


def test_recommendation_selector_returns_explicit_conflict_and_missing_outcomes() -> None:
    component = ComponentDef(
        mpn="CONFLICT",
        passive_recommendations=[_recommendation("datasheet", 1e-6), _recommendation("datasheet", 2.2e-6)],
    )

    assert component.select_passive_recommendation("regulator_io_cap", "decoupling").outcome == "conflict"
    assert component.select_passive_recommendation("crystal_cap", "load").outcome == "missing"


def test_recommendation_selector_prefers_exact_net_then_global() -> None:
    component = ComponentDef(
        mpn="NET_SELECTOR",
        passive_recommendations=[
            _recommendation("datasheet", 1e-6),
            _recommendation("datasheet", 4.7e-6, net="VIN"),
        ],
    )

    exact = component.select_passive_recommendation("regulator_io_cap", "decoupling", net="VIN")
    fallback = component.select_passive_recommendation("regulator_io_cap", "decoupling", net="VOUT")
    assert exact.recommendation is not None and exact.recommendation.value == pytest.approx(4.7e-6)
    assert fallback.recommendation is not None and fallback.recommendation.value == pytest.approx(1e-6)


def test_recommendation_selector_refuses_value_outside_fallback_bounds() -> None:
    component = ComponentDef(
        mpn="OUT_OF_BOUNDS",
        passive_recommendations=[_recommendation("datasheet", 10e-6, fallback_bounds=(100e-9, 1e-6))],
    )

    assert component.select_passive_recommendation("regulator_io_cap", "decoupling").outcome == "out_of_bounds"


def test_recommendation_normalization_deduplicates_legacy_alias_on_replace() -> None:
    legacy = {"net": "VIN", "value": "1uF"}
    component = ComponentDef(
        mpn="DEDUPLICATED",
        datasheet_url="https://example.test/datasheet.pdf",
        passive_recommendations=[legacy],
        recommended_bypass=[legacy],
    )

    assert len(component.passive_recommendations) == 1
    assert len(replace(component).passive_recommendations) == 1


def test_support_passive_traceability_is_compatible_and_validated() -> None:
    cap = BypassCap("1", "VIN", "GND", "1uF", "C_0402")
    strap = StrapConfig("2", "EN", "GND", "10k", "R_0402")
    assert cap.presentation == "topology_local"
    assert strap.presentation == "topology_local"

    traced = BypassCap(
        "1",
        "VIN",
        "GND",
        "1uF",
        "C_0402",
        selection_policy="datasheet",
        confidence="single_source",
        evidence_ids=["EV-CALCULATION-abcdefabcdef"],
        calculation_id="CALC-DATASHEET_SELECTION-abcdefabcdef",
    )
    assert traced.evidence_ids == ("EV-CALCULATION-abcdefabcdef",)
    with pytest.raises(ValueError, match="evidence_ids"):
        BypassCap("1", "VIN", "GND", "1uF", "C_0402", evidence_ids=["bogus"])
    with pytest.raises(ValueError, match="cannot be marked withheld"):
        StrapConfig(
            "2",
            "EN",
            "GND",
            "10k",
            "R_0402",
            withheld_finding_id="CW-PSV-001-abcdefabcdef",
            eligibility="withheld",
        )
