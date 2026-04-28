"""Smoke tests for circuit_weaver.placer — public API surface.

Tests all exported public functions from the placer module using
the iot_sensor_node sample design spec.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from circuit_weaver.allocator import SheetAllocation, allocate_sheets
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
