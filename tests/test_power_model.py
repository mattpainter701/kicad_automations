"""Typed power-domain normalization and component hydration contracts."""

import pytest

from circuit_weaver.component_db import ComponentDef, ComponentRegistry, PinDef, PowerReq
from circuit_weaver.design_ir import (
    DesignBlock,
    DesignIR,
    PowerDomain,
    design_ir_to_engine_spec,
    design_ir_to_spec,
    normalize_design_spec,
)
from circuit_weaver.generational_repair import auto_repair_design
from circuit_weaver.project_spec import resolve_project_spec
from circuit_weaver.schema import get_design_ir_schema
from circuit_weaver.symbol_resolver import SymbolResolver


def test_power_domain_round_trip_preserves_only_declared_envelope_values() -> None:
    ir = normalize_design_spec({
        "project": "power-contract",
        "blocks": [],
        "power_domains": [{
            "net": "VBAT",
            "v_min": 3.0,
            "v_nominal": 3.7,
            "v_max": 4.2,
            "direction": "source",
            "i_peak_ma": 1200,
            "sequencing": {"order": 1},
            "provenance": {"evidence_id": "EV-DATASHEET-1"},
        }, {"net": "VDD_AUX"}],
    })

    battery, aux = ir.power_domains
    assert battery.sequence_order == 1
    assert battery.evidence_id == "EV-DATASHEET-1"
    assert battery.i_steady_ma is None
    assert aux.v_nominal is None

    serialized = design_ir_to_spec(ir)
    assert serialized["power_domains"][0]["v_nominal"] == 3.7
    assert "i_steady_ma" not in serialized["power_domains"][0]
    assert serialized["power_domains"][1] == {"net": "VDD_AUX"}
    assert design_ir_to_engine_spec(ir)["power_domains"] == serialized["power_domains"]


def test_legacy_power_req_positional_values_are_explicit_aliases_not_limits() -> None:
    legacy = PowerReq("VIN", 5.0, 500.0)
    assert legacy.v_nominal == 5.0
    assert legacy.i_peak_ma == 500.0
    assert legacy.v_min is None
    assert legacy.v_max is None
    assert legacy.tolerance is None


def test_component_power_envelope_ingests_through_resolver() -> None:
    registry = ComponentRegistry()
    registry.register(ComponentDef(
        mpn="POWER_TEST",
        pins=[PinDef("1", "VDD", "power_in", "L")],
        power_pins={"1": "VDD"},
    ))
    components, _ = resolve_project_spec({
        "project": "power-contract",
        "digital": [{
            "ic": "POWER_TEST",
            "ref": "U1",
            "power_reqs": [{
                "net": "VDD",
                "v_min": 3.1,
                "v_nominal": 3.3,
                "v_max": 3.5,
                "direction": "load",
                "i_peak_ma": 90,
                "i_steady_ma": 40,
                "sequencing": {"order": 2, "dependency": "VIN"},
                "tolerance": 0.05,
                "provenance": {"evidence_id": "EV-U1-PWR"},
            }],
            "power_pin_defs": [{"pin": "1", "net": "VDD", "direction": "load"}],
            "dropout_voltage": 0.25,
        }],
    }, component_reg=registry)

    component = components[0]
    req = component.power_reqs[0]
    assert (req.v_min, req.v_nominal, req.v_max) == (3.1, 3.3, 3.5)
    assert (req.i_peak_ma, req.i_steady_ma) == (90, 40)
    assert (req.sequence_order, req.sequence_dependency, req.evidence_id) == (2, "VIN", "EV-U1-PWR")
    assert component.typed_power_pins()[0].direction == "load"
    assert component.dropout_voltage == 0.25


def test_cached_power_req_keeps_unknown_values_unknown() -> None:
    component = SymbolResolver()._rebuild_from_cache("CACHED_POWER", {
        "power_reqs": [{"net": "VIN", "v_nominal": 5.0, "i_peak_ma": 300}],
    })
    assert component is not None
    req = component.power_reqs[0]
    assert (req.v_nominal, req.i_peak_ma) == (5.0, 300)
    assert req.v_min is None and req.v_max is None and req.i_steady_ma is None


def test_schema_exposes_optional_typed_power_domains() -> None:
    domain = get_design_ir_schema()["properties"]["power_domains"]["items"]
    assert domain["properties"]["v_nominal"]["type"] == "number"
    assert domain["properties"]["direction"]["enum"] == ["source", "load", "bidirectional"]
    assert domain["properties"]["i_peak_ma"]["minimum"] == 0
    assert "v_nominal" not in domain["required"]


@pytest.mark.parametrize("domain", [
    {"net": "VDD", "direction": "invalid"},
    {"net": "VDD", "v_min": 3.4, "v_nominal": 3.3},
    {"net": "VDD", "i_peak_ma": -1},
])
def test_power_domain_rejects_invalid_declared_envelopes(domain: dict) -> None:
    with pytest.raises(ValueError):
        normalize_design_spec({"project": "invalid-power", "blocks": [], "power_domains": [domain]})


def test_auto_repair_keeps_declared_power_domains() -> None:
    ir = DesignIR(
        blocks=[DesignBlock(
            id="digital:U1", section="digital", kind="template", ref="U1", template_type="mcu",
            params={"vdd_net": "VDD", "sda_net": "I2C_SDA", "scl_net": "I2C_SCL"},
        )],
        power_domains=[PowerDomain(net="VDD", v_nominal=3.3, direction="source")],
    )
    component = ComponentDef(
        mpn="MCU", source_ref="U1",
        pins=[PinDef("1", "SDA", "bidirectional", "L"), PinDef("2", "SCL", "bidirectional", "L")],
        pin_nets={"1": "I2C_SDA", "2": "I2C_SCL"}, power_pins={"3": "VDD"},
    )
    repaired, _, actions = auto_repair_design(ir, [component], enabled=True)
    assert actions
    assert repaired.power_domains == ir.power_domains
