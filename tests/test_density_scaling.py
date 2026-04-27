"""Sprint 43 T201 — density-scaled grid spacing in placer.py.

The `_density_scaled_gaps` function scales inter-component row/column gaps
so that components spread across available page area instead of clustering
in a corner. This test verifies the scaling behavior.
"""

from __future__ import annotations

from circuit_weaver.component_db import ComponentDef, PinDef
from circuit_weaver.placer import _density_scaled_gaps
from circuit_weaver.primitives import snap


def _mk_ic(ref: str, pin_count: int = 8) -> ComponentDef:
    side_cycle = ["L", "R", "T", "B"]
    pins = [
        PinDef(number=str(i + 1), name=f"P{i}", electrical_type="bidirectional", side=side_cycle[i % 4])
        for i in range(pin_count)
    ]
    return ComponentDef(
        mpn=f"MPN_{ref}",
        ref_prefix="U",
        category="digital",
        description=f"Test IC {ref}",
        pins=pins,
        source_ref=ref,
        footprint="Package_QFP:LQFP-48_7x7mm_P0.5mm",
    )


# --------------------------------------------------------------------------
# Basic scaling behavior
# --------------------------------------------------------------------------


def test_no_scaling_for_small_sheet():
    """A4 sheet with 5 ICs: components fill enough of the page that no scaling applies."""
    components = [_mk_ic(f"U{i}", 8) for i in range(5)]
    col, row = _density_scaled_gaps(
        components, base_col_gap=12.07, base_row_gap=20.32,
        paper_width=297, usable_height=180, x_start=20,
    )
    # Small sheet, moderate component count — gaps should stay at or near base
    assert col == 12.07
    assert row == 20.32


def test_scaling_on_large_sheet_with_modest_components():
    """A0 sheet (1189x841mm) with 15 average ICs: should scale gaps up."""
    components = [_mk_ic(f"U{i}", 12) for i in range(15)]
    col, row = _density_scaled_gaps(
        components, base_col_gap=12.07, base_row_gap=20.32,
        paper_width=1189, usable_height=811, x_start=20,
    )
    # Large paper, low fill → gaps should be scaled up
    assert col > 12.07, f"Expected col_gap > 12.07 on large sheet, got {col}"
    assert row > 20.32, f"Expected row_gap > 20.32 on large sheet, got {row}"
    # Cap at 3.0x
    assert col <= 12.07 * 3.0, f"col_gap {col} exceeds 3.0x base"
    assert row <= 20.32 * 3.0, f"row_gap {row} exceeds 3.0x base"


def test_no_scaling_below_three_components():
    """< 3 components: return base gaps unchanged."""
    components = [_mk_ic("U1", 8)]
    col, row = _density_scaled_gaps(
        components, base_col_gap=12.07, base_row_gap=20.32,
        paper_width=1189, usable_height=811, x_start=20,
    )
    assert col == 12.07
    assert row == 20.32


def test_no_scaling_when_already_dense():
    """If components already fill > 35% of page, don't compress or scale."""
    components = [_mk_ic(f"U{i}", 80) for i in range(40)]
    col, row = _density_scaled_gaps(
        components, base_col_gap=12.07, base_row_gap=20.32,
        paper_width=297, usable_height=180, x_start=20,
    )
    # Dense layout on small sheet — no scaling applied (fill > 35%)
    assert col == 12.07
    assert row == 20.32


def test_output_is_snapped_to_grid():
    """All gap outputs should round-trip through snap() without changing."""
    components = [_mk_ic(f"U{i}", 10) for i in range(12)]
    col, row = _density_scaled_gaps(
        components, base_col_gap=12.07, base_row_gap=20.32,
        paper_width=1189, usable_height=811, x_start=20,
    )
    # snap() already applied in _density_scaled_gaps; verify it's idempotent
    assert abs(col - snap(col)) < 0.001, f"col_gap {col} not already snapped"
    assert abs(row - snap(row)) < 0.001, f"row_gap {row} not already snapped"
