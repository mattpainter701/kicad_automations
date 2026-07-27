"""Independent fixed-number oracle checks for T246 passive synthesis."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from circuit_weaver.calc import (
    apply_e_series_selection,
    apply_ratio_preserving_divider_selection,
    bounded_fallback_scalar,
    crystal_effective_load,
    crystal_external_load_cap,
    datasheet_selected_scalar,
    feedback_divider_top,
    is_selection_eligible,
    ldo_minimum_capacitor,
    rc_cutoff,
    termination_resistor_match,
)

CORPUS = Path(__file__).parents[1] / "benchmarks" / "electrical" / "passives"


def _oracle() -> dict:
    return json.loads((CORPUS / "oracle-cases.json").read_text(encoding="utf-8"))


def test_passive_oracle_schema_provenance_and_producer_verification_are_explicit():
    schema = json.loads((CORPUS / "oracle.schema.json").read_text(encoding="utf-8"))
    oracle = _oracle()
    required = set(schema["properties"]["cases"]["items"]["required"])

    assert oracle["schema_version"] == schema["properties"]["schema_version"]["const"]
    assert oracle["authoring_source"] == "independent_reference"
    assert len(oracle["cases"]) >= 10
    assert len({case["id"] for case in oracle["cases"]}) == len(oracle["cases"])
    for case in oracle["cases"]:
        assert required <= set(case)
        assert case["provenance"]["license"] == "CC0-1.0"
        assert case["provenance"]["rationale"]
        assert case["producer_integration"]["status"] == "verified"
        assert case["producer_integration"]["reason"]


@pytest.mark.parametrize("case", _oracle()["cases"], ids=lambda case: case["id"])
def test_current_calculation_substrate_matches_fixed_passive_oracles(case):
    inputs = case["inputs"]
    expected = case["expected"]
    operation = case["operation"]
    target = f"param:U1.oracle.{case['id'].replace('-', '_')}"

    if operation == "feedback_divider":
        top = feedback_divider_top(
            target=target,
            vout_v=inputs["target_vout_v"],
            vref_v=inputs["vref_v"],
            r_bottom_ohm=inputs["bottom_ohm"],
        )
        bottom = datasheet_selected_scalar(
            target=target.replace("oracle.", "oracle_bottom."),
            value=inputs["bottom_ohm"],
            unit="ohm",
            evidence_id="EV-DATASHEET-aaaaaaaaaaaa",
        )
        selected = apply_ratio_preserving_divider_selection(
            top,
            bottom,
            target_vout_v=inputs["target_vout_v"],
            vref_v=inputs["vref_v"],
            series=inputs["series"],
            max_scale_factor=inputs["max_scale_factor"],
        )
        tolerance = expected["absolute_tolerance_v"]
        assert top.raw_result.value == pytest.approx(expected["raw_top_ohm"], abs=1e-9)
        assert selected.top.chosen_value.value == pytest.approx(expected["chosen_top_ohm"], abs=1e-9)
        assert selected.bottom.chosen_value.value == pytest.approx(expected["chosen_bottom_ohm"], abs=1e-9)
        assert selected.realized_vout_v == pytest.approx(expected["realized_vout_v"], abs=tolerance)
    elif operation == "datasheet_scalar":
        selected = datasheet_selected_scalar(target=target, **inputs)
        assert selected.policy == expected["policy"]
        assert selected.confidence == expected["confidence"]
        assert selected.chosen_value.value == pytest.approx(
            expected["chosen_value"], abs=expected["absolute_tolerance"]
        )
    elif operation == "ldo_minimum_capacitor":
        decision = ldo_minimum_capacitor(target=target, **inputs)
        assert decision.finding is None
        assert decision.calculation.chosen_value.value == pytest.approx(
            expected["chosen_capacitance_f"], abs=expected["absolute_tolerance_f"]
        )
        assert decision.calculation.margin.value == pytest.approx(
            expected["headroom_f"], abs=expected["absolute_tolerance_f"]
        )
    elif operation == "crystal_load":
        raw = crystal_external_load_cap(
            target=target,
            load_capacitance_f=inputs["load_capacitance_f"],
            stray_capacitance_f=inputs["stray_capacitance_f"],
        )
        selected = apply_e_series_selection(raw, series=inputs["series"], direction=inputs["direction"])
        effective = crystal_effective_load(
            target=target.replace("oracle.", "oracle_effective."),
            capacitance_1_f=selected.chosen_value.value,
            capacitance_2_f=selected.chosen_value.value,
            stray_capacitance_f=inputs["stray_capacitance_f"],
        )
        tolerance = expected["absolute_tolerance_f"]
        assert raw.raw_result.value == pytest.approx(expected["raw_external_cap_f"], abs=tolerance)
        assert selected.chosen_value.value == pytest.approx(expected["chosen_external_cap_f"], abs=tolerance)
        assert effective.raw_result.value == pytest.approx(expected["effective_load_f"], abs=tolerance)
    elif operation == "termination":
        selected = termination_resistor_match(target=target, **inputs)
        assert selected.chosen_value.value == pytest.approx(
            expected["chosen_ohm"], abs=expected["absolute_tolerance_ohm"]
        )
    elif operation == "rc_cutoff":
        calculated = rc_cutoff(target=target, **inputs)
        assert calculated.raw_result.value == pytest.approx(
            expected["cutoff_hz"], abs=expected["absolute_tolerance_hz"]
        )
    elif operation == "bounded_fallback_adverse":
        decision = bounded_fallback_scalar(target=target, **inputs)
        assert decision.finding is not None
        assert decision.finding.rule_id == expected["finding_rule_id"]
        assert is_selection_eligible(decision.calculation) is expected["selection_eligible"]
    else:  # pragma: no cover - schema/case review should keep operations closed
        raise AssertionError(f"unsupported passive oracle operation: {operation}")
