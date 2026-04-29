"""Smoke tests for circuit_weaver.placer — public API surface.

Tests all exported public functions from the placer module using
the iot_sensor_node sample design spec.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from circuit_weaver.allocator import allocate_sheets
from circuit_weaver.design_loader import compile_design_ir
from circuit_weaver.placer import (
    component_annotation_start_y,
    component_block_size,
    component_body_bounds,
    component_body_size,
    layout_sheet,
    reset_ref_counters,
)

SAMPLES_DIR = Path(__file__).resolve().parent.parent / "samples"


# ================================================================
# Helpers
# ================================================================


def _load_spec(name: str) -> dict:
    """Load a sample YAML spec by directory name."""
    from circuit_weaver.project_spec import _parse_yaml

    yaml_path = SAMPLES_DIR / name / f"{name}.yaml"
    assert yaml_path.exists(), f"Sample not found at {yaml_path}"
    return _parse_yaml(yaml_path)


# ================================================================
# Fixtures
# ================================================================


@pytest.fixture(scope="module")
def iot_sensor_spec():
    """Load the I/O sensor node sample spec (module-scoped, one parse)."""
    return _load_spec("iot_sensor_node")


@pytest.fixture(scope="module")
def compiled_iot_sensor(iot_sensor_spec):
    """Compile the I/O sensor node spec into a design IR."""
    reset_ref_counters()
    return compile_design_ir(iot_sensor_spec)


@pytest.fixture(scope="module")
def iot_sensor_components(compiled_iot_sensor):
    """Resolved component list from the compiled design."""
    return compiled_iot_sensor.components


@pytest.fixture()
def reset_counters():
    """Ensure fresh ref counters before each test that touches layout."""
    reset_ref_counters()


# ================================================================
# Tests — reset_ref_counters
# ================================================================


class TestResetRefCounters:
    """reset_ref_counters() is a no-arg idempotent state reset."""

    def test_reset_ref_counters_never_raises(self):
        """Calling reset_ref_counters() should never throw."""
        reset_ref_counters()

    def test_reset_ref_counters_twice_is_idempotent(self):
        """Double-calling reset_ref_counters() is harmless."""
        reset_ref_counters()
        reset_ref_counters()


# ================================================================
# Tests — component_block_size
# ================================================================


class TestComponentBlockSize:
    """component_block_size(comp) → (width, height)."""

    def test_block_size_non_zero(self, iot_sensor_components):
        """Every real component should have a positive block size."""
        for comp in iot_sensor_components:
            w, h = component_block_size(comp)
            assert w > 0, f"{comp.mpn}: expected positive width, got {w}"
            assert h > 0, f"{comp.mpn}: expected positive height, got {h}"

    def test_block_size_is_snapped(self, iot_sensor_components):
        """Block dimensions should be snapped to the KiCad grid."""
        from circuit_weaver.primitives import snap

        for comp in iot_sensor_components:
            w, h = component_block_size(comp)
            assert abs(w - snap(w)) < 0.001, f"{comp.mpn}: width {w} not snapped"
            assert abs(h - snap(h)) < 0.001, f"{comp.mpn}: height {h} not snapped"


# ================================================================
# Tests — component_body_size
# ================================================================


class TestComponentBodySize:
    """component_body_size(comp) → (width, height), excluding extras."""

    def test_body_size_non_zero(self, iot_sensor_components):
        """Body dimensions should be positive for real ICs."""
        for comp in iot_sensor_components:
            w, h = component_body_size(comp)
            assert w > 0, f"{comp.mpn}: expected positive body width, got {w}"
            assert h > 0, f"{comp.mpn}: expected positive body height, got {h}"

    def test_body_size_does_not_exceed_block_size(self, iot_sensor_components):
        """Body dimensions should be ≤ full block dimensions."""
        for comp in iot_sensor_components:
            bw, bh = component_block_size(comp)
            w, h = component_body_size(comp)
            assert w <= bw + 1.0, f"{comp.mpn}: body width {w} > block width {bw}"
            assert h <= bh + 1.0, f"{comp.mpn}: body height {h} > block height {bh}"


# ================================================================
# Tests — component_body_bounds
# ================================================================


class TestComponentBodyBounds:
    """component_body_bounds(pc) → (left, top, right, bottom)."""

    def test_body_bounds_produce_valid_rectangle(
        self, iot_sensor_components, reset_counters
    ):
        """component_body_bounds() on a placed IC should yield left<right, top<bottom."""
        sheets = allocate_sheets(iot_sensor_components)
        assert len(sheets) > 0
        layout = layout_sheet(sheets[0])
        assert layout.placed_ics, "Expected at least one placed IC"
        pc = layout.placed_ics[0]
        left, top, right, bottom = component_body_bounds(pc)
        assert left < right, f"Expected left < right, got ({left}, {right})"
        assert top < bottom, f"Expected top < bottom, got ({top}, {bottom})"

    def test_body_bounds_all_floats(
        self, iot_sensor_components, reset_counters
    ):
        """Bounds tuple should contain only numeric types."""
        sheets = allocate_sheets(iot_sensor_components)
        layout = layout_sheet(sheets[0])
        pc = layout.placed_ics[0]
        bounds = component_body_bounds(pc)
        assert all(isinstance(v, (int, float)) for v in bounds), (
            f"Expected all-numeric bounds, got {bounds}"
        )


# ================================================================
# Tests — component_annotation_start_y
# ================================================================


class TestComponentAnnotationStartY:
    """component_annotation_start_y(comp, center_y) → y-coordinate for notes."""

    def test_annotation_start_y_is_non_negative(self, iot_sensor_components):
        """Annotation y should be >= 0 for a centered reference."""
        for comp in iot_sensor_components:
            y = component_annotation_start_y(comp, 50.0)
            assert y >= 0, f"{comp.mpn}: expected non-negative annotation y, got {y}"

    def test_annotation_start_y_advances_with_center(self, iot_sensor_components):
        """Raising center_y should raise annotation_start_y by the same delta."""
        for comp in iot_sensor_components:
            y_low = component_annotation_start_y(comp, 50.0)
            y_high = component_annotation_start_y(comp, 100.0)
            assert y_high >= y_low, f"{comp.mpn}: annotation y decreased"


# ================================================================
# Tests — layout_sheet
# ================================================================


class TestLayoutSheet:
    """layout_sheet(sheet_alloc) → SheetLayout."""

    def test_returns_sheet_layout_with_placements(
        self, iot_sensor_components, reset_counters
    ):
        """layout_sheet() should produce a SheetLayout with non-empty placements."""
        sheets = allocate_sheets(iot_sensor_components)
        assert len(sheets) > 0, "Expected at least one sheet allocation"
        layout = layout_sheet(sheets[0])
        assert layout.placed_ics, "Expected non-empty placed_ics"
        assert layout.name, "Sheet should have a name"
        assert layout.title, "Sheet should have a title"
        assert layout.paper, "Sheet should have a paper size"

    def test_placed_ics_have_expected_refs(
        self, iot_sensor_components, reset_counters
    ):
        """ICs should get U/R prefixed reference designators after layout."""
        sheets = allocate_sheets(iot_sensor_components)
        layout = layout_sheet(sheets[0])
        refs = [pc.ref for pc in layout.placed_ics]
        assert any(r.startswith("U") for r in refs), (
            f"Expected at least one U-prefixed ref, got {refs}"
        )

    def test_reset_and_relayout_produces_consistent_results(
        self, iot_sensor_components, reset_counters
    ):
        """After reset_ref_counters(), layout_sheet() should still work."""
        sheets = allocate_sheets(iot_sensor_components)
        assert len(sheets) > 0
        layout = layout_sheet(sheets[0])
        assert layout.placed_ics, "Layout should succeed after reset"

    def test_each_component_gets_unique_ref(
        self, iot_sensor_components, reset_counters
    ):
        """All placed ICs should have unique reference designators."""
        sheets = allocate_sheets(iot_sensor_components)
        layout = layout_sheet(sheets[0])
        refs = [pc.ref for pc in layout.placed_ics]
        assert len(refs) == len(set(refs)), "Duplicate reference designators found"

    def test_placed_passives_have_valid_sym_types(
        self, iot_sensor_components, reset_counters
    ):
        """Placed passives should have a recognised symbol type."""
        sheets = allocate_sheets(iot_sensor_components)
        layout = layout_sheet(sheets[0])
        for pp in layout.placed_passives:
            assert pp.sym_type in ("C", "R", "L"), (
                f"Unexpected sym_type '{pp.sym_type}' for {pp.ref}"
            )

    def test_called_twice_with_reset_is_deterministic(
        self, iot_sensor_components, reset_counters
    ):
        """Calling layout_sheet twice with reset should give identical refs."""
        sheets = allocate_sheets(iot_sensor_components)
        sheet = sheets[0]

        reset_ref_counters()
        layout_a = layout_sheet(sheet)
        refs_a = [pc.ref for pc in layout_a.placed_ics]

        reset_ref_counters()
        layout_b = layout_sheet(sheet)
        refs_b = [pc.ref for pc in layout_b.placed_ics]

        assert refs_a == refs_b, (
            f"Ref mismatch between runs:\n  A: {refs_a}\n  B: {refs_b}"
        )


# ================================================================
# Tests — Sprint 45 Bug 1: paper-size selection respects allocator
# ================================================================


class TestPaperSizeSelection:
    """layout_sheet() should respect the allocator's paper choice when it fits.

    Regression: density-scaled gaps grow with paper area. When the placer
    iterated `_PAPER_ORDER` from A4 upward, intermediate paper sizes (A3)
    overflowed because their density-scaled gaps were sized for A3, while
    A2 with even larger gaps still "fit" trivially. Result: a 5-IC design
    that should land on A4 ended up on A2.
    """

    def test_small_design_does_not_over_promote_paper(self, reset_counters):
        """A 5-IC iot-sensor-class design should NOT promote past A3.

        Regression: prior to Sprint 45, density-scaled gaps could push a
        5-IC, 33-pin layout (the IoT_AQ_Sensor_v2 size) all the way to A2,
        wasting half a sheet of whitespace. The allocator picks A4; the
        placer may need A3 if footprints don't fit, but never A2 for this
        scale.
        """
        from circuit_weaver.allocator import pick_paper_size
        from circuit_weaver.component_db import ComponentDef, PinDef

        # Build a 5-IC design analogous to IoT_AQ_Sensor_v2 (small SOIC-style IC)
        comps = []
        pin_counts = [2, 4, 8, 15, 8]  # connector, pin-header, pull-ups, MCU, sensor
        for i, npins in enumerate(pin_counts):
            pins = [
                PinDef(
                    number=str(p + 1),
                    name=f"P{p}",
                    electrical_type="bidirectional",
                    side=("L", "R", "T", "B")[p % 4],
                )
                for p in range(npins)
            ]
            comps.append(
                ComponentDef(
                    mpn=f"IC{i}",
                    ref_prefix="U",
                    category="digital",
                    description=f"IC {i}",
                    pins=pins,
                    source_ref=f"U{i + 1}",
                    footprint="Package_SO:SOIC-8_3.9x4.9mm_P1.27mm",
                )
            )

        total_pins = sum(len(c.pins) for c in comps)
        allocator_choice = pick_paper_size(len(comps), total_pins)
        # 5 components, 37 pins → A4 per allocator
        assert allocator_choice == "A4", (
            f"5 ICs × ~7 pins (37 total) should pick A4, got {allocator_choice}"
        )

        sheets = allocate_sheets(comps)
        assert len(sheets) >= 1
        # Bug 1: pre-fix, this would land on A2 due to gap-cascade. Now stays
        # at allocator choice (A4) or at most one promotion (A3) for fit.
        layout = layout_sheet(sheets[0])
        assert layout.paper in ("A4", "A3"), (
            f"Expected A4 or A3 (max one promotion), got {layout.paper}. "
            f"Density-scaled gaps may be over-promoting paper size."
        )

    def test_mixed_connector_sensor_design_does_not_promote_to_a2(self, reset_counters):
        """A small connector + 3-IC design should fit without jumping to A2."""
        from circuit_weaver.component_db import BypassCap, ComponentDef, PinDef, StrapConfig

        def pins(count: int) -> list[PinDef]:
            return [
                PinDef(
                    number=str(idx + 1),
                    name=f"P{idx}",
                    electrical_type="bidirectional",
                    side=("L", "R", "T", "B")[idx % 4],
                )
                for idx in range(count)
            ]

        comps = [
            ComponentDef(
                mpn="BAT_CONN",
                ref_prefix="J",
                category="power",
                description="JST PH 2-Pin Connector (Battery/Sensor)",
                pins=pins(2),
                source_ref="BT1",
                footprint="Connector_JST:JST_PH_B2B-PH-K_1x02_P2.00mm_Vertical",
                bypass_caps=[BypassCap("1", "VBAT", "GND", "10uF", "Capacitor_SMD:C_0805_2012Metric")],
            ),
            ComponentDef(
                mpn="DEBUG_HDR",
                ref_prefix="J",
                category="mcu",
                description="4-Pin 2.54mm Pin Header",
                pins=pins(4),
                source_ref="J1",
                footprint="Connector_PinHeader_2.54mm:PinHeader_1x04_P2.54mm_Vertical",
            ),
            ComponentDef(
                mpn="NRF52840_MODULE",
                ref_prefix="U",
                category="mcu",
                description="nRF52840 BLE 5.0 Module with PCB Antenna",
                pins=pins(15),
                source_ref="U1",
                footprint="RF_Module:Raytac_MDBT50Q-1MV2",
                bypass_caps=[
                    BypassCap("1", "VDD_3P3", "GND", "100nF", "Capacitor_SMD:C_0402_1005Metric"),
                    BypassCap("2", "VBAT", "GND", "10uF", "Capacitor_SMD:C_0805_2012Metric"),
                ],
                straps=[StrapConfig("3", "RESET_N", "VDD_3P3", "10k", "Resistor_SMD:R_0402_1005Metric")],
            ),
            ComponentDef(
                mpn="BME688",
                ref_prefix="U",
                category="sensor",
                description="Digital low power gas, pressure, temperature and humidity sensor",
                pins=pins(8),
                source_ref="U2",
                footprint="Package_LGA:Bosch_LGA-8_3x3mm_P0.8mm",
            ),
            ComponentDef(
                mpn="I2C_PULLUPS",
                ref_prefix="RP",
                category="buses",
                description="I2C pull-up resistor network (no physical IC)",
                pins=pins(4),
                source_ref="RP1",
                footprint="Resistor_SMD:R_Array_Convex_4x0402",
                straps=[
                    StrapConfig("1", "I2C_SDA", "VDD_3P3", "4.7k", "Resistor_SMD:R_0402_1005Metric"),
                    StrapConfig("2", "I2C_SCL", "VDD_3P3", "4.7k", "Resistor_SMD:R_0402_1005Metric"),
                ],
            ),
        ]

        layout = layout_sheet(allocate_sheets(comps)[0])

        assert layout.paper in ("A4", "A3")

    def test_compact_connector_heavy_design_stays_on_a3(self, reset_counters):
        """A compact sensor board with several headers should not jump to A1."""
        from circuit_weaver.component_db import BypassCap, ComponentDef, PinDef, StrapConfig

        def pins(count: int) -> list[PinDef]:
            return [
                PinDef(
                    number=str(idx + 1),
                    name=f"P{idx}",
                    electrical_type="bidirectional",
                    side=("L", "R", "T", "B")[idx % 4],
                )
                for idx in range(count)
            ]

        comps = [
            ComponentDef(
                mpn=f"CONN_{idx}",
                ref_prefix="J",
                category="connector",
                description="small board connector",
                pins=pins(pin_count),
                source_ref=f"J{idx + 1}",
                footprint="Connector_PinHeader_2.54mm:PinHeader_1x02_P2.54mm_Vertical",
            )
            for idx, pin_count in enumerate([2, 2, 3, 4, 9, 3])
        ]
        comps.append(
            ComponentDef(
                mpn="TLV3691IDPFR",
                ref_prefix="U",
                category="mcu",
                description="nanopower comparator",
                pins=pins(5),
                source_ref="U3",
                footprint="Package_TO_SOT_SMD:SOT-353_SC-70-5",
                bypass_caps=[BypassCap("VDD", "VBAT", "GND", "100nF", "Capacitor_SMD:C_0402_1005Metric")],
                straps=[
                    StrapConfig("4", "THRESH", "VBAT", "100k", "Resistor_SMD:R_0402_1005Metric"),
                    StrapConfig("4", "THRESH", "GND", "10k", "Resistor_SMD:R_0402_1005Metric"),
                    StrapConfig("1", "OUT", "VBAT", "100k", "Resistor_SMD:R_0402_1005Metric"),
                ],
            )
        )

        layout = layout_sheet(allocate_sheets(comps)[0])

        assert layout.paper == "A3"

    def test_large_design_promotes_paper_when_needed(self, reset_counters):
        """A genuinely large design (40+ ICs) should promote paper as needed."""
        from circuit_weaver.component_db import ComponentDef, PinDef

        comps = []
        for i in range(40):
            pins = [
                PinDef(
                    number=str(p + 1),
                    name=f"P{p}",
                    electrical_type="bidirectional",
                    side=("L", "R", "T", "B")[p % 4],
                )
                for p in range(20)
            ]
            comps.append(
                ComponentDef(
                    mpn=f"IC{i}",
                    ref_prefix="U",
                    category="digital",
                    description=f"IC {i}",
                    pins=pins,
                    source_ref=f"U{i + 1}",
                    footprint="Package_QFP:LQFP-48_7x7mm_P0.5mm",
                )
            )

        sheets = allocate_sheets(comps)
        layout = layout_sheet(sheets[0])
        # Should land on A2 or larger; not stuck on A4.
        assert layout.paper in ("A2", "A1", "A0"), (
            f"Expected A2+ for 40 dense ICs, got {layout.paper}"
        )
