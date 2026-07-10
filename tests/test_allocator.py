"""Dedicated tests for circuit_weaver.allocator."""

from __future__ import annotations

import pytest

from circuit_weaver.allocator import (
    SheetAllocation,
    allocate_sheets,
    classify_component,
    partition_review_sheets,
    pick_paper_size,
)
from circuit_weaver.component_db import BypassCap, ComponentDef, PresentationWiringPolicy, StrapConfig


def _pins(count: int) -> list:
    from circuit_weaver.component_db import PinDef

    return [
        PinDef(number=str(i + 1), name=f"P{i}", electrical_type="bidirectional", side=("L", "R", "T", "B")[i % 4])
        for i in range(count)
    ]


def _comp(
    ref: str,
    *,
    category: str = "digital",
    ref_prefix: str = "U",
    description: str = "",
    pins: int = 8,
    presentation_group: str = "",
    functional_section: str = "",
    bypass_caps: list[BypassCap] | None = None,
    straps: list[StrapConfig] | None = None,
    template_annotations: list[str] | None = None,
) -> ComponentDef:
    return ComponentDef(
        mpn=ref,
        ref_prefix=ref_prefix,
        category=category,
        description=description,
        source_ref=ref,
        pins=_pins(pins),
        presentation_group=presentation_group,
        functional_section=functional_section,
        bypass_caps=bypass_caps or [],
        straps=straps or [],
        template_annotations=template_annotations or [],
    )


@pytest.mark.parametrize(
    ("count", "pins", "expected"),
    [
        (5, 40, "A4"),
        (6, 40, "A3"),
        (15, 120, "A3"),
        (16, 120, "A2"),
        (40, 300, "A2"),
        (41, 300, "A1"),
        (80, 800, "A1"),
        (81, 800, "A0"),
    ],
)
def test_pick_paper_size_thresholds(count, pins, expected):
    assert pick_paper_size(count, pins) == expected


@pytest.mark.parametrize(
    ("component", "expected"),
    [
        (_comp("PWR", category="power"), "power"),
        (_comp("MCU", category="digital"), "mcu"),
        (_comp("FPGA", category="fpga"), "fpga"),
        (_comp("RF", category="rf"), "rf"),
        (_comp("SENS", category="sensor"), "sensors"),
        (_comp("CONN", category="connector"), "connectors"),
        (_comp("PASS", category="passive", ref_prefix="J"), "connectors"),
        (_comp("LED", category="passive", ref_prefix="D", description="green LED"), "debug"),
        (_comp("DESC", category="unknown", description="temperature humidity sensor"), "misc"),
    ],
)
def test_classify_component_categories_and_ref_fallbacks(component, expected):
    assert classify_component(component) == expected


def test_classify_component_description_fallbacks_for_unknown_category():
    assert classify_component(_comp("U1", category="custom", description="buck regulator")) == "power"
    assert classify_component(_comp("U2", category="custom", description="BLE wifi module")) == "mcu"
    assert classify_component(_comp("U3", category="custom", description="serial flash memory")) == "storage"
    assert classify_component(_comp("U4", category="custom", description="usb uart bridge")) == "comm"
    assert classify_component(_comp("U5", category="custom", description="mystery part")) == "misc"


def test_allocate_sheets_empty_returns_empty_list():
    assert allocate_sheets([]) == []


def test_small_design_allocates_single_main_sheet_with_support_passives():
    bypass = BypassCap("1", "VDD", "GND", "100nF", "C_0402")
    strap = StrapConfig("2", "BOOT", "VDD", "10k", "R_0402")
    comps = [
        _comp("U1", bypass_caps=[bypass], straps=[strap], template_annotations=["MCU note"]),
        _comp("U2", template_annotations=["MCU note", "Sensor note"]),
    ]

    sheets = allocate_sheets(comps)

    assert len(sheets) == 1
    sheet = sheets[0]
    assert sheet.name == "main"
    assert sheet.title == "Schematic"
    assert sheet.components == comps
    assert sheet.bypass_caps == [bypass]
    assert sheet.straps == [strap]
    assert sheet.sheet_annotations == ["MCU note", "Sensor note"]


def test_large_design_splits_by_category_and_sorts_power_first():
    comps = [
        _comp("U1", category="sensor"),
        _comp("U2", category="power"),
        _comp("U3", category="digital"),
        _comp("U4", category="usb"),
        _comp("U5", category="connector", ref_prefix="J"),
        _comp("U6", category="storage"),
        _comp("U7", category="rf"),
        _comp("U8", category="clock"),
        _comp("U9", category="transceiver"),
    ]

    sheets = allocate_sheets(comps, single_sheet_threshold=2)
    names = [s.name for s in sheets]

    assert names[0] == "power"
    assert "mcu" in names
    assert "sensors" in names
    assert "connectors" in names
    assert "usb" in names
    assert "storage" in names


def test_passive_only_sheet_merges_into_power_sheet():
    comps = [
        _comp("U1", category="power"),
        _comp("R1", category="misc", ref_prefix="R", pins=2),
        _comp("C1", category="misc", ref_prefix="C", pins=2),
        _comp("L1", category="misc", ref_prefix="L", pins=2),
    ]
    comps[0].power_pins = {"1": "VDD"}
    comps[1].power_pins = {"1": "VDD"}

    sheets = allocate_sheets(comps, single_sheet_threshold=1)

    assert [s.name for s in sheets] == ["power"]
    assert {c.source_ref for c in sheets[0].components} == {"U1", "R1", "C1", "L1"}


def test_real_ic_misc_sheet_does_not_merge():
    comps = [
        _comp("U1", category="power"),
        _comp("U2", category="misc", ref_prefix="U", pins=8),
    ]

    sheets = allocate_sheets(comps, single_sheet_threshold=1)

    assert [s.name for s in sheets] == ["power", "misc"]


def test_partition_review_sheets_splits_large_grouped_sheet():
    group_a = [_comp(f"UA{i}", pins=80, presentation_group="MCU Cluster") for i in range(2)]
    group_b = [_comp(f"UB{i}", pins=80, presentation_group="Sensor Cluster") for i in range(2)]
    sheet = SheetAllocation(
        name="main",
        title="Schematic",
        paper="A2",
        components=group_a + group_b,
        sheet_annotations=["top note"],
        presentation_wiring_policy=PresentationWiringPolicy(),
    )

    out = partition_review_sheets([sheet])

    assert len(out) == 2
    assert out[0].name == "main"
    assert out[0].sheet_annotations == ["top note"]
    assert out[1].name == "main_sensor_cluster"
    assert out[1].sheet_annotations == []
    assert out[1].title.startswith("Schematic")
    assert out[1].title.endswith("Sensor Cluster")


def test_partition_review_sheets_splits_small_explicit_groups():
    sheet = SheetAllocation(
        name="main",
        title="Schematic",
        paper="A4",
        components=[_comp("U1", pins=20, presentation_group="A"), _comp("U2", pins=20, presentation_group="B")],
    )

    partitioned = partition_review_sheets([sheet])
    assert len(partitioned) == 2
    assert {comp.presentation_group for part in partitioned for comp in part.components} == {"A", "B"}


def test_small_design_partitions_explicit_functional_sections_with_support_owned() -> None:
    power_cap = BypassCap("1", "VDD", "GND", "100nF", "C_0402")
    mcu_strap = StrapConfig("2", "BOOT", "GND", "10k", "R_0402")
    power = _comp("U1", category="power", functional_section="power", bypass_caps=[power_cap])
    mcu = _comp("U2", category="digital", functional_section="digital", straps=[mcu_strap])
    sensor = _comp("U3", category="sensor", functional_section="sensors")

    sheets = allocate_sheets([power, mcu, sensor])

    assert [sheet.name for sheet in sheets] == ["power", "mcu", "sensors"]
    by_name = {sheet.name: sheet for sheet in sheets}
    assert by_name["power"].bypass_caps == [power_cap]
    assert by_name["power"].straps == []
    assert by_name["mcu"].straps == [mcu_strap]
    assert by_name["mcu"].bypass_caps == []


def test_allocate_small_design_partitions_presentation_groups() -> None:
    sheets = allocate_sheets(
        [
            _comp("U1", presentation_group="Core Processing"),
            _comp("U2", presentation_group="External IO"),
        ]
    )

    assert [sheet.name for sheet in sheets] == ["core_processing", "external_io"]
    assert [sheet.title for sheet in sheets] == ["Core Processing", "External Io"]


def test_explicit_passive_only_functional_section_is_not_merged() -> None:
    sheets = allocate_sheets(
        [
            _comp("U1", category="power", functional_section="power"),
            _comp(
                "R1",
                category="passive",
                ref_prefix="R",
                pins=2,
                functional_section="user_interface",
            ),
        ]
    )

    assert [sheet.name for sheet in sheets] == ["power", "user_interface"]
    assert all(sheet.explicit_group for sheet in sheets)


def test_support_parts_count_toward_render_planning() -> None:
    bypass_caps = [BypassCap(str(index), "VDD", "GND", "100nF", "C_0402") for index in range(20)]
    sheet = allocate_sheets([_comp("U1", pins=8, bypass_caps=bypass_caps)])[0]

    assert sheet.render_component_count == 21
    assert sheet.render_pin_count == 48
    assert sheet.paper == "A2"


def test_partition_review_sheets_does_not_split_single_group():
    sheet = SheetAllocation(
        name="main",
        title="Schematic",
        paper="A2",
        components=[_comp("U1", pins=220, presentation_group="A")],
    )

    assert partition_review_sheets([sheet]) == [sheet]


def test_allocate_sheets_recomputes_paper_after_merge():
    power = _comp("U1", category="power", pins=30)
    passives = [_comp(f"R{i}", category="misc", ref_prefix="R", pins=2) for i in range(20)]
    sheets = allocate_sheets([power, *passives], single_sheet_threshold=1)

    assert len(sheets) == 1
    assert sheets[0].name == "power"
    assert sheets[0].paper == pick_paper_size(21, 70)


def test_sheet_template_annotations_dedupe_preserves_first_seen_order():
    comps = [
        _comp("U1", template_annotations=["A", "B"]),
        _comp("U2", template_annotations=["B", "C"]),
    ]

    sheets = allocate_sheets(comps)

    assert sheets[0].sheet_annotations == ["A", "B", "C"]
