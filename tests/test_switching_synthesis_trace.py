"""T246 switching-regulator producer traceability contracts."""

from __future__ import annotations

import pytest

from circuit_weaver.ic_data import get_ic_data
from circuit_weaver.subcircuits.topology_builders import build_switching_regulator
from circuit_weaver.validator import _validate_feedback_dividers


@pytest.mark.parametrize(
    ("mpn", "params"),
    [
        ("AP62300", {"vin": 12.0, "vout": 3.3, "iout": 1.0, "ref": "U1"}),
        ("TPS61230A", {"vin": 3.3, "vout": 12.0, "iout": 1.0, "ref": "U2"}),
        ("TPS63020", {"vin": 3.3, "vout": 5.0, "iout": 1.0, "ref": "U3"}),
    ],
)
def test_switching_synthesis_retains_closed_trace_for_every_emitted_passive(mpn, params):
    component = build_switching_regulator(get_ic_data(mpn), params).components[0]
    calculations = {record.id: record for record in component.passive_synthesis_calculations}
    evidence = {record.id for record in component.passive_synthesis_evidence}

    assert calculations
    assert evidence
    for passive in [*component.bypass_caps, *component.straps]:
        assert passive.selection_policy is not None
        assert passive.confidence is not None
        assert passive.calculation_id in calculations
        assert passive.evidence_ids
        assert set(passive.evidence_ids) <= evidence

    for record in calculations.values():
        assert record.emits_evidence in evidence
        assert all(
            input_value.evidence_id is None or input_value.evidence_id in evidence for input_value in record.inputs
        )


def test_switching_feedback_pair_is_joint_e96_selection_and_self_validates():
    component = build_switching_regulator(
        get_ic_data("AP62300"), {"vin": 12.0, "vout": 3.3, "iout": 1.0, "ref": "U1"}
    ).components[0]
    top, bottom = component.straps
    records = {record.id: record for record in component.passive_synthesis_calculations}

    for record in (records[top.calculation_id], records[bottom.calculation_id]):
        assert record.snap_policy is not None
        assert record.snap_policy.series == "E96"
        assert record.snap_policy.direction == "ratio_preserving"
        assert record.margin is not None
        assert "2x_leg_scale" in record.margin.kind
    assert _validate_feedback_dividers([component]) == []


def test_switching_invalid_feedback_bottom_fails_closed_before_network_emission():
    with pytest.raises(ValueError, match=r"CW-PSV-002"):
        build_switching_regulator(
            get_ic_data("AP62300"), {"vin": 12.0, "vout": 3.3, "iout": 1.0, "r_fbb": 0.1, "ref": "U1"}
        )
