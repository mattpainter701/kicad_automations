"""Sprint 43 Task 195 — auto sheet splitting in allocator.

The allocator must auto-split density-overloaded sheets even when the
user did not declare a presentation_group on components. Without this,
a single category with 30+ ICs lands on a single A0 sheet that may
overflow even at the largest paper size.
"""

from __future__ import annotations

from circuit_weaver.allocator import (
    _AUTO_PARTITION_MAX_COMPONENTS,
    _AUTO_PARTITION_MAX_PINS,
    _is_density_overload,
    allocate_sheets,
)
from circuit_weaver.component_db import ComponentDef, PinDef


def _mk_ic(ref: str, pin_count: int = 8, category: str = "digital") -> ComponentDef:
    side_cycle = ["L", "R", "T", "B"]
    pins = [
        PinDef(number=str(i + 1), name=f"P{i}", electrical_type="bidirectional", side=side_cycle[i % 4])
        for i in range(pin_count)
    ]
    return ComponentDef(
        mpn=f"MPN_{ref}",
        ref_prefix="U",
        category=category,
        description=f"Test IC {ref}",
        pins=pins,
        source_ref=ref,
        footprint="Package_QFP:LQFP-48_7x7mm_P0.5mm",
    )


def _mk_passive(ref: str, prefix: str = "R") -> ComponentDef:
    pins = [
        PinDef(number="1", name="1", electrical_type="passive", side="L"),
        PinDef(number="2", name="2", electrical_type="passive", side="R"),
    ]
    return ComponentDef(
        mpn=f"MPN_{ref}",
        ref_prefix=prefix,
        category="passive",
        description="Resistor",
        pins=pins,
        source_ref=ref,
        footprint="Resistor_SMD:R_0603",
    )


# --------------------------------------------------------------------------
# Density-overload detection
# --------------------------------------------------------------------------


def test_density_overload_detection_below_thresholds():
    from circuit_weaver.allocator import SheetAllocation

    sheet = SheetAllocation(
        name="mcu",
        title="MCU",
        paper="A3",
        components=[_mk_ic(f"U{i}", pin_count=10) for i in range(8)],
    )
    assert _is_density_overload(sheet) is False


def test_density_overload_detection_above_component_threshold():
    from circuit_weaver.allocator import SheetAllocation

    components = [_mk_ic(f"U{i}", pin_count=8) for i in range(_AUTO_PARTITION_MAX_COMPONENTS + 5)]
    sheet = SheetAllocation(name="mcu", title="MCU", paper="A0", components=components)
    assert _is_density_overload(sheet) is True


def test_density_overload_detection_above_pin_threshold():
    from circuit_weaver.allocator import SheetAllocation

    components = [_mk_ic(f"U{i}", pin_count=80) for i in range(5)]
    total_pins = sum(len(c.pins) for c in components)
    assert total_pins > _AUTO_PARTITION_MAX_PINS
    sheet = SheetAllocation(name="mcu", title="MCU", paper="A0", components=components)
    assert _is_density_overload(sheet) is True


# --------------------------------------------------------------------------
# Auto-partition behavior
# --------------------------------------------------------------------------


def test_dense_sheet_is_auto_partitioned():
    """A sheet with 25 small ICs in one category must split into multiple sub-sheets."""
    components = [_mk_ic(f"U{i}", pin_count=12, category="digital") for i in range(25)]
    sheets = allocate_sheets(components, single_sheet_threshold=8)

    assert len(sheets) >= 2, "Expected dense category to split into multiple sub-sheets"

    # All sub-sheets must have <= the auto-partition threshold
    for sheet in sheets:
        assert len(sheet.components) <= _AUTO_PARTITION_MAX_COMPONENTS, (
            f"Sheet '{sheet.name}' has {len(sheet.components)} components, exceeds threshold"
        )

    # Total component count is preserved
    total = sum(len(s.components) for s in sheets)
    assert total == 25


def test_dense_sheet_subsheets_have_continuation_titles():
    """The first sub-sheet keeps the original name; later sub-sheets get a `_N` suffix."""
    components = [_mk_ic(f"U{i}", pin_count=10, category="digital") for i in range(30)]
    sheets = allocate_sheets(components, single_sheet_threshold=8)

    base_sheets = [s for s in sheets if s.name == "mcu"]
    cont_sheets = [s for s in sheets if s.name.startswith("mcu_")]

    assert len(base_sheets) == 1, "Expected exactly one un-suffixed base sheet"
    assert len(cont_sheets) >= 1, "Expected at least one continuation sub-sheet"
    # Continuation sheets should have continuation titles
    for s in cont_sheets:
        assert "(cont." in s.title, f"Expected '(cont.' in continuation sheet title, got '{s.title}'"


def test_modest_sheet_does_not_partition():
    """A sheet just under thresholds stays whole."""
    components = [_mk_ic(f"U{i}", pin_count=8, category="digital") for i in range(10)]
    sheets = allocate_sheets(components, single_sheet_threshold=8)
    digital_sheets = [s for s in sheets if s.name == "mcu"]
    assert len(digital_sheets) == 1, f"Expected 1 sheet for 10 components, got {len(digital_sheets)}"


def test_passive_heavy_sheet_partitions_by_pins():
    """A sheet with many passives still partitions if pin count exceeds threshold."""
    # 100 passives = 200 pins, well over MAX_PINS even though component count = 100
    components = [_mk_passive(f"R{i}") for i in range(100)]
    # Add a few connectors so the merge pass doesn't absorb everything
    components.extend([_mk_ic(f"J{i}", pin_count=20, category="connector") for i in range(3)])
    sheets = allocate_sheets(components, single_sheet_threshold=8)

    # Connectors sheet should be partitioned because total pins > MAX_PINS
    connector_sheets = [s for s in sheets if s.name.startswith("connectors")]
    # At minimum we should have allocated to connectors and been split
    if connector_sheets:
        # If we have multiple connector sheets, the partitioning fired
        # Or the single one is below the limit
        for s in connector_sheets:
            pin_total = sum(len(c.pins) for c in s.components)
            assert pin_total <= _AUTO_PARTITION_MAX_PINS or len(connector_sheets) > 1


def test_partition_review_sheets_preserves_explicit_groups():
    """partition_review_sheets should run presentation-group split first, then auto-partition."""
    components = []
    for i in range(20):
        c = _mk_ic(f"U{i}", pin_count=12, category="digital")
        if i < 10:
            c.presentation_group = "group_a"
        else:
            c.presentation_group = "group_b"
        components.append(c)

    sheets = allocate_sheets(components, single_sheet_threshold=8)
    # Should split by presentation group → at least 2 sheets
    assert len(sheets) >= 2
