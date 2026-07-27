from __future__ import annotations

import json

from circuit_weaver.component_db import ComponentDef, PinDef, PowerReq
from circuit_weaver.placement_context import build_placement_context, write_placement_context


def _component(ref: str, category: str, mpn: str, nets: dict[str, str]) -> ComponentDef:
    return ComponentDef(
        mpn=mpn,
        source_ref=ref,
        category=category,
        footprint="Package_QFN:QFN-16",
        pins=[PinDef(number=pin, name=net, electrical_type="bidirectional", side="L") for pin, net in nets.items()],
        pin_nets=nets,
    )


def test_context_contains_targeted_research_and_primary_references():
    components = [
        _component("U1", "power", "TPS62130", {"1": "VIN", "2": "SW"}),
        _component("U2", "rf", "NRF52840", {"1": "VDD", "2": "USB_DP", "3": "USB_DM"}),
        _component("J1", "usb", "USB-C", {"1": "USB_DP", "2": "USB_DM"}),
    ]
    placements = {
        "U1": {"x": 10, "y": 10, "rotation": 0, "layer": "front"},
        "U2": {"x": 40, "y": 20, "rotation": 0, "layer": "front"},
        "J1": {"x": 50, "y": 39, "rotation": 0, "layer": "front"},
    }

    context = build_placement_context(
        components,
        placements,
        board_width_mm=60,
        board_height_mm=40,
    )

    assert context["artifact_kind"] == "placement_review_context"
    assert "official datasheets" in context["authority"]
    assert {item["topic"] for item in context["references"]} >= {"power", "rf", "usb", "decoupling"}
    assert {item["ref"] for item in context["research_queries"]} == {"U1", "U2", "J1"}
    assert any(net["name"] == "USB_DP" for net in context["critical_nets"])


def test_context_records_support_parent_affinity_and_writes_json(tmp_path):
    parent = _component("U1", "digital", "MCU", {"1": "VDD"})
    cap = _component("C1", "passive", "100nF", {"1": "VDD", "2": "GND"})
    cap.placement_parent_ref = "U1"
    cap.placement_role = "decoupling"

    context = build_placement_context(
        [parent, cap],
        {
            "U1": {"x": 20, "y": 20, "rotation": 0, "layer": "front"},
            "C1": {"x": 23, "y": 20, "rotation": 0, "layer": "front"},
        },
        board_width_mm=50,
        board_height_mm=40,
    )
    affinity = next(rule for rule in context["rules"] if rule["kind"] == "parent_affinity")
    assert affinity["targets"] == ["C1", "U1"]
    assert affinity["priority"] == "critical"

    path = write_placement_context(context, tmp_path / "placement_context.json")
    assert json.loads(path.read_text(encoding="utf-8"))["components"][1]["ref"] == "U1"


def test_context_uses_source_mpn_and_exposes_sourcing_and_constraint_blockers():
    component = _component("U1", "digital", "REGISTRY_ALIAS", {"1": "DATA"})
    component.source_mpn = "REAL-MPN"
    support = _component("C1", "passive", "", {"1": "VDD", "2": "GND"})
    support.assembly_source_kind = "bypass"
    support.placement_sourcing_status = "review_blocked"
    support.placement_sourcing_review_reason = "Assign an orderable capacitor."

    context = build_placement_context(
        [component, support],
        {
            "U1": {"x": 10, "y": 10, "rotation": 0, "layer": "front"},
            "C1": {"x": 14, "y": 10, "rotation": 0, "layer": "front"},
        },
        board_width_mm=40,
        board_height_mm=30,
        constraint_evaluation={
            "unsupported": [
                {"target": "U1", "reason": "Placement prose cannot be applied safely."}
            ]
        },
    )

    row = next(item for item in context["components"] if item["ref"] == "U1")
    assert row["mpn"] == "REAL-MPN"
    assert context["research_queries"][0]["query"].startswith("REAL-MPN ")
    assert context["review_gate"]["status"] == "blocked"
    assert {blocker["kind"] for blocker in context["review_gate"]["blockers"]} == {
        "sourcing_metadata",
        "placement_constraint",
    }


def test_context_exposes_component_official_reference_and_suppresses_virtual_query():
    physical = ComponentDef(
        mpn="MCU-1",
        source_ref="U1",
        category="mcu",
        footprint="Package_QFN:QFN-16",
        pins=[PinDef(number="1", name="DATA", electrical_type="bidirectional", side="L")],
        pin_nets={"1": "DATA"},
        official_references=[
            {
                "title": "MCU-1 hardware design guide",
                "url": "https://manufacturer.example/MCU-1-layout.pdf",
                "publisher": "Example Semiconductor",
            }
        ],
    )
    virtual = _component("RP1", "buses", "PULLUPS_ONLY", {"1": "DATA"})
    virtual.footprint = ""
    virtual.placement_geometry_status = "review_blocked_placeholder"

    context = build_placement_context(
        [physical, virtual],
        {
            "U1": {"x": 10, "y": 10, "rotation": 0, "layer": "front"},
            "RP1": {"x": 15, "y": 10, "rotation": 0, "layer": "front"},
        },
        board_width_mm=30,
        board_height_mm=25,
    )

    assert {query["ref"] for query in context["research_queries"]} == {"U1"}
    specific = next(reference for reference in context["references"] if reference.get("ref") == "U1")
    assert specific["source"] == "component_metadata"
    assert specific["url"] == "https://manufacturer.example/MCU-1-layout.pdf"


def test_context_serializes_declared_power_envelopes_without_false_defaults():
    component = _component("U1", "power", "REGULATOR", {"1": "VBAT", "2": "VDD_3P3"})
    component.power_reqs = [
        PowerReq(
            "VBAT", v_min=3.0, v_nominal=3.7, v_max=4.2, direction="source",
            i_steady_ma=250, i_peak_ma=500, sequence_order=1,
            sequence_dependency="battery_present", tolerance=0.05, evidence_id="EV-DATASHEET-123456789abc",
        )
    ]
    context = build_placement_context(
        [component], {"U1": {"x": 10, "y": 10, "rotation": 0, "layer": "front"}},
        board_width_mm=30, board_height_mm=20,
    )
    envelope = context["components"][0]["power_envelopes"][0]
    assert envelope["v_min"] == 3.0
    assert envelope["i_peak_ma"] == 500
    assert envelope["sequence_dependency"] == "battery_present"
    assert context["power_domains"] == [{"ref": "U1", **envelope}]


def test_legacy_max_current_remains_peak_not_inferred_steady_current():
    component = _component("U1", "digital", "LOAD", {"1": "VDD_3P3"})
    component.power_reqs = [PowerReq("VDD_3P3", 3.3, 500)]

    context = build_placement_context(
        [component],
        {"U1": {"x": 10, "y": 10, "rotation": 0, "layer": "front"}},
        board_width_mm=30,
        board_height_mm=20,
    )

    envelope = context["components"][0]["power_envelopes"][0]
    assert "i_steady_ma" not in envelope
    assert envelope["i_peak_ma"] == 500
