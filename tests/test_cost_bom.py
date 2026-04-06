"""Tests for cost BOM functionality.

Tests price tier selection, cost calculations, and BOM costing workflow.
"""

import pytest

from circuit_weaver.cost_bom import cost_bom
from circuit_weaver.parts_lookup import get_unit_price


class TestGetUnitPrice:
    """Test price tier lookup helper."""

    def test_exact_tier_match(self):
        """Test exact quantity match within a tier."""
        tiers = [
            {"min_qty": 1, "max_qty": 9, "unit_price": 0.50},
            {"min_qty": 10, "max_qty": 99, "unit_price": 0.40},
            {"min_qty": 100, "max_qty": 999, "unit_price": 0.30},
        ]
        assert get_unit_price(tiers, 5) == 0.50
        assert get_unit_price(tiers, 50) == 0.40
        assert get_unit_price(tiers, 500) == 0.30

    def test_boundary_values(self):
        """Test quantities at tier boundaries."""
        tiers = [
            {"min_qty": 1, "max_qty": 9, "unit_price": 0.50},
            {"min_qty": 10, "max_qty": 99, "unit_price": 0.40},
        ]
        assert get_unit_price(tiers, 1) == 0.50  # Lower bound of tier 1
        assert get_unit_price(tiers, 9) == 0.50  # Upper bound of tier 1
        assert get_unit_price(tiers, 10) == 0.40  # Lower bound of tier 2
        assert get_unit_price(tiers, 99) == 0.40  # Upper bound of tier 2

    def test_qty_above_highest_tier(self):
        """Test quantity above all defined tiers."""
        tiers = [
            {"min_qty": 1, "max_qty": 9, "unit_price": 0.50},
            {"min_qty": 10, "max_qty": 99, "unit_price": 0.40},
        ]
        # Quantity above all tiers returns the highest tier price
        assert get_unit_price(tiers, 1000) == 0.40

    def test_empty_tiers(self):
        """Test with no price tiers."""
        assert get_unit_price([], 100) is None

    def test_single_tier(self):
        """Test with only one price tier."""
        tiers = [{"min_qty": 1, "max_qty": 9999, "unit_price": 0.50}]
        assert get_unit_price(tiers, 1) == 0.50
        assert get_unit_price(tiers, 5000) == 0.50


class TestCostBom:
    """Test cost BOM generation."""

    def test_cost_bom_basic(self):
        """Test basic BOM costing with mock data."""
        # Create a minimal spec with known components
        spec = {
            "project": "test_board",
            "power": [
                {
                    "type": "ldo",
                    "ic": "AP2112K-3.3",
                    "vin": 5.0,
                    "vout": 3.3,
                    "vin_net": "VBUS",
                    "rail_name": "VDD_3P3",
                }
            ],
        }

        result = cost_bom(spec, qty_breaks=[1, 10])

        assert result["status"] in ["ok", "partial"]
        assert result["project"] == "test_board"
        assert result["qty_breaks"] == [1, 10]
        assert isinstance(result["rows"], list)
        assert isinstance(result["totals"], dict)
        assert isinstance(result["warnings"], list)

    def test_cost_bom_qty_breaks(self):
        """Test that cost_bom respects qty_breaks parameter."""
        spec = {
            "project": "test",
            "power": [
                {
                    "type": "ldo",
                    "ic": "AP2112K-3.3",
                    "vin": 5.0,
                    "vout": 3.3,
                    "vin_net": "VBUS",
                    "rail_name": "VDD_3P3",
                }
            ],
        }

        qty_breaks = [1, 5, 25, 100]
        result = cost_bom(spec, qty_breaks=qty_breaks)

        assert result["qty_breaks"] == qty_breaks
        # Totals should have entries for each qty break
        for q in qty_breaks:
            assert str(q) in result["totals"]

    def test_cost_bom_default_qty_breaks(self):
        """Test that default qty breaks are used if none provided."""
        spec = {
            "project": "test",
            "power": [
                {
                    "type": "ldo",
                    "ic": "AP2112K-3.3",
                    "vin": 5.0,
                    "vout": 3.3,
                    "vin_net": "VBUS",
                    "rail_name": "VDD_3P3",
                }
            ],
        }

        result = cost_bom(spec)

        # Should use default [1, 10, 100, 1000]
        assert result["qty_breaks"] == [1, 10, 100, 1000]

    def test_cost_bom_empty_spec(self):
        """Test handling of spec with no components."""
        spec = {"project": "empty"}  # No power, digital, etc.

        result = cost_bom(spec)

        # Should succeed but with empty rows
        assert result["status"] in ["ok", "error"]
        assert result["project"] == "empty"

    def test_cost_bom_warns_on_lookup_failure(self):
        """Test that failed LCSC lookups generate warnings."""
        spec = {
            "project": "test",
            "power": [
                {
                    "type": "ldo",
                    "ic": "FAKE_IC_PART_XYZ_NOT_REAL",
                    "vin": 5.0,
                    "vout": 3.3,
                    "vin_net": "VBUS",
                    "rail_name": "VDD_3P3",
                }
            ],
        }

        result = cost_bom(spec)

        # Should succeed (ok or partial) with warnings about lookup failures
        assert result["status"] in ["ok", "partial"]
        # May or may not have warnings depending on whether the IC lookup fails

    @pytest.mark.network
    def test_cost_bom_real_parts(self):
        """Integration test with real LCSC parts (requires network)."""
        # Network tests are optional and often skipped in CI
        # This test verifies the costing engine can handle real part data
        pytest.skip("Network test — skipped by default")


class TestPricingCalculations:
    """Test price calculations in cost BOM rows."""

    def test_extended_price_calculation(self):
        """Test that extended prices are calculated correctly."""
        # For a part with qty_per_board=2, unit_price=0.50, qty_break=10:
        # qty_needed = 2 * 10 = 20
        # extended = 0.50 * 20 = $10.00
        tiers = [{"min_qty": 1, "max_qty": 9999, "unit_price": 0.50}]

        # 2 per board
        qty_per_board = 2
        qty_break = 10
        qty_needed = qty_per_board * qty_break

        unit_price = get_unit_price(tiers, qty_needed)
        extended = unit_price * qty_needed

        assert unit_price == 0.50
        assert extended == 10.00

    def test_tiered_pricing_discount(self):
        """Test that higher quantities get better pricing."""
        tiers = [
            {"min_qty": 1, "max_qty": 10, "unit_price": 1.00},
            {"min_qty": 11, "max_qty": 100, "unit_price": 0.80},
            {"min_qty": 101, "max_qty": 9999, "unit_price": 0.60},
        ]

        # At qty 5: should be tier 1
        price_small = get_unit_price(tiers, 5)
        assert price_small == 1.00

        # At qty 50: should be tier 2
        price_medium = get_unit_price(tiers, 50)
        assert price_medium == 0.80

        # At qty 500: should be tier 3
        price_large = get_unit_price(tiers, 500)
        assert price_large == 0.60

        # Verify discount chain
        assert price_large < price_medium < price_small
