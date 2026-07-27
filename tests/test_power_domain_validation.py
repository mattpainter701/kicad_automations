from types import SimpleNamespace

import pytest

from circuit_weaver.component_db import ComponentDef, PowerReq
from circuit_weaver.dispatcher import _validate_typed_power_envelopes


def _component(ref: str, requirements: list[dict], **attributes):
    component = ComponentDef(mpn=f"TEST-{ref}", source_ref=ref)
    component.power_reqs = []
    for raw in requirements:
        req = PowerReq(net=raw["net"], voltage=raw.get("voltage", 0.0))
        for key, value in raw.items():
            setattr(req, key, value)
        component.power_reqs.append(req)
    for key, value in attributes.items():
        setattr(component, key, value)
    return component


def _compiled(domains: dict[str, dict], components: list[ComponentDef]):
    normalized = [dict(value, net=net) for net, value in domains.items()]
    return SimpleNamespace(ir=SimpleNamespace(power_domains=normalized), components=components)


def _codes(compiled):
    return {issue.code for issue in _validate_typed_power_envelopes(compiled)}


def test_voltage_envelope_detects_over_and_under_voltage_with_calculations():
    component = _component("U1", [{"net": "VDD", "v_min": 3.0, "v_max": 3.6}])
    compiled = _compiled({"VDD": {"v_min": 2.8, "v_max": 3.8}}, [component])

    issues = _validate_typed_power_envelopes(compiled)

    assert {issue.code for issue in issues} == {"power-over-voltage", "power-under-voltage"}
    for issue in issues:
        assert issue.calculation["rule_id"].startswith("CW-PWR-")
        assert issue.calculation["observed"]
        assert issue.calculation["expected"]
        assert issue.calculation["equation"] == "power-envelope-comparison/v1"
        assert issue.calculation["margin"]["unit"] == "V"


def test_sparse_envelope_omits_unknown_inputs_and_labels_margin_units():
    component = _component("U1", [{"net": "VDD", "v_max": 3.6}])
    compiled = _compiled({"VDD": {"v_max": 3.8}}, [component])

    issue = _validate_typed_power_envelopes(compiled)[0]

    assert issue.code == "power-over-voltage"
    assert issue.calculation["inputs"] == {
        "rail": "VDD",
        "rail_v_max": {"value": 3.8, "unit": "V"},
        "component_v_max": {"value": 3.6, "unit": "V"},
    }
    assert issue.calculation["margin"]["unit"] == "V"
    assert issue.calculation["margin"]["value"] == pytest.approx(-0.2)


def test_missing_range_is_inconclusive_not_false_precision():
    component = _component("U1", [{"net": "VDD", "voltage": 3.3}])
    compiled = _compiled({"VDD": {"v_nominal": 5.0}}, [component])

    assert _codes(compiled) == set()


def test_detects_source_contention_reverse_flow_and_current_budget():
    source_a = _component("U1", [{"net": "SYS", "direction": "source", "i_steady_ma": 100}])
    source_b = _component("U2", [{"net": "SYS", "direction": "source", "i_steady_ma": 100}])
    load = _component("U3", [{"net": "SYS", "direction": "load", "i_steady_ma": 250}])
    compiled = _compiled({"SYS": {"direction": "load"}}, [source_a, source_b, load])

    issues = _validate_typed_power_envelopes(compiled)
    assert {issue.code for issue in issues} == {"power-source-contention", "power-reverse-flow", "power-current-budget"}
    assert {issue.calculation["margin"]["unit"] for issue in issues if "margin" in issue.calculation} == {
        "count",
        "mA",
    }


def test_detects_dropout_and_sequencing_violation():
    regulator = _component(
        "U1",
        [{"net": "VIN", "direction": "load"}, {"net": "VOUT", "direction": "source"}],
        dropout_voltage=0.3,
    )
    compiled = _compiled(
        {
            "VIN": {"v_min": 3.4, "sequencing": {"order": 2}},
            "VOUT": {"v_max": 3.3, "sequencing": {"order": 1, "dependencies": ["VIN"]}},
        },
        [regulator],
    )

    assert _codes(compiled) == {"power-regulator-dropout", "power-sequencing"}
