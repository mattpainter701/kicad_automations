"""Tests for enhanced design scoring."""

import pytest

from circuit_weaver.design_ir import DesignBlock, DesignIR
from circuit_weaver.design_scorer import (
    DetailedElectricalQualityScore,
    score_design_comprehensive,
)


@pytest.fixture
def minimal_design_ir():
    """Create a minimal DesignIR with basic structure."""
    return DesignIR(
        metadata={
            "project": "Test Project",
            "version": "1.0",
            "description": "Test design",
        },
        blocks=[
            DesignBlock(
                id="psu:reg:abc123",
                section="power",
                kind="template",
                ref="U1",
                template_type="LDO_3V3",
                ic="AMS1117",
                value="3.3V",
                description="3.3V Linear Regulator",
                mpn="AMS1117-3.3",
            ),
            DesignBlock(
                id="psu:cap_bulk:def456",
                section="power",
                kind="component",
                ref="C1",
                value="100µF",
                description="Bulk Capacitor",
                mpn="GRM31CR61A106KA19L",
            ),
            DesignBlock(
                id="io:pullup:ghi789",
                section="interfaces",
                kind="component",
                ref="R1",
                value="4.7k",
                description="I2C Pull-up",
                mpn="RC0805FR-074K7L",
            ),
            DesignBlock(
                id="mcu:stm32:jkl012",
                section="mcu",
                kind="component",
                ref="U2",
                value="STM32H743",
                description="ARM Microcontroller",
                mpn="STM32H743VIT6",
            ),
        ],
        interfaces=[],
        approved_overrides=[],
        pcb_constraints=[],
    )


@pytest.fixture
def detailed_design_ir():
    """Create a comprehensive DesignIR with diverse components."""
    return DesignIR(
        metadata={
            "project": "Complex Design",
            "version": "2.0",
            "description": "Full-featured design",
            "operating_temp": "-40 to +85°C",
        },
        blocks=[
            # Power section
            DesignBlock(
                id="psu:boost:001",
                section="power",
                kind="template",
                ref="U1",
                template_type="BOOST_5V",
                ic="TPS61023",
                value="5V",
                description="Boost Converter SMPS",
                mpn="TPS61023DRLR",
            ),
            DesignBlock(
                id="psu:ldo:002",
                section="power",
                kind="template",
                ref="U2",
                template_type="LDO_3V3",
                ic="AMS1117",
                value="3.3V",
                description="3.3V LDO Regulator",
                mpn="AMS1117-3.3",
            ),
            DesignBlock(
                id="psu:cap_bulk1:003",
                section="power",
                kind="component",
                ref="C1",
                value="100µF",
                description="Bulk Capacitor",
                mpn="GRM31CR61A106KA19L",
            ),
            DesignBlock(
                id="psu:cap_bulk2:004",
                section="power",
                kind="component",
                ref="C2",
                value="47µF",
                description="Bulk Capacitor",
                mpn="GRM21BR61A476KE19L",
            ),
            DesignBlock(
                id="psu:cap_decouple:005",
                section="power",
                kind="component",
                ref="C3",
                value="100nF",
                description="Decoupling Capacitor",
                mpn="GRM155R71C104KA88D",
            ),
            # Signal integrity
            DesignBlock(
                id="io:i2c_pullup1:006",
                section="interfaces",
                kind="component",
                ref="R1",
                value="4.7k",
                description="I2C Pull-up",
                mpn="RC0805FR-074K7L",
            ),
            DesignBlock(
                id="io:i2c_pullup2:007",
                section="interfaces",
                kind="component",
                ref="R2",
                value="4.7k",
                description="I2C Pull-up",
                mpn="RC0805FR-074K7L",
            ),
            # MCU
            DesignBlock(
                id="mcu:stm32:008",
                section="mcu",
                kind="component",
                ref="U3",
                value="STM32H743",
                description="ARM Microcontroller",
                mpn="STM32H743VIT6",
            ),
            # USB interface
            DesignBlock(
                id="io:usb:009",
                section="interfaces",
                kind="template",
                ref="J1",
                template_type="USB_TypeC",
                ic="USB-C Connector",
                value="USB 2.0",
                description="USB Type-C Connector",
                mpn="USB4085-GF-A",
            ),
        ],
        interfaces=[],
        approved_overrides=[
            {
                "kind": "approved_substitution",
                "target": "STM32H743VIT6",
                "replacement": "STM32H753VIT6",
            }
        ],
        pcb_constraints=[
            {
                "kind": "placement",
                "target": "U2",
                "description": "LDO near decaps",
            },
            {
                "kind": "diff_pair",
                "target": "USB_DM/DP",
                "length_match": "within 10mm",
            },
            {
                "kind": "keepout",
                "target": "antenna_area",
                "description": "Keep analog away",
            },
        ],
    )


class TestDetailedElectricalQualityScore:
    """Test the score dataclass."""

    def test_score_creation(self):
        """Create a score object."""
        score = DetailedElectricalQualityScore(
            power_integrity=85,
            signal_integrity=92,
            placement_quality=78,
            thermal=90,
            manufacturing=88,
            overall=86.6,
            grade="B",
        )
        assert score.power_integrity == 85
        assert score.grade == "B"

    def test_score_to_dict(self):
        """Convert score to dictionary."""
        score = DetailedElectricalQualityScore(
            power_integrity=85,
            signal_integrity=92,
            placement_quality=78,
            thermal=90,
            manufacturing=88,
            overall=86.6,
            grade="B",
        )
        d = score.to_dict()
        assert d["power"] == 85.0
        assert d["overall"] == 86.6
        assert d["grade"] == "B"

    def test_summary_with_gaps(self):
        """Generate summary text."""
        score = DetailedElectricalQualityScore(
            power_integrity=70,  # Below 75
            signal_integrity=92,
            placement_quality=78,
            thermal=50,  # Below 75
            manufacturing=88,
            overall=75.6,
            grade="C",
            section_details={
                "power_gaps": "Missing bulk capacitors",
                "thermal_gaps": "No thermal vias specified",
            },
        )
        summary = score.summary_with_gaps()
        assert "Design Score: 75.6 (C)" in summary
        assert "⚠ BELOW TARGET" in summary
        assert "Recommendations:" in summary
        assert "Power:" in summary
        assert "Thermal:" in summary


class TestPowerIntegrityScoring:
    """Test power integrity scoring."""

    def test_power_score_with_bulk_caps(self, minimal_design_ir):
        """Score improves with bulk capacitors."""
        score_result = score_design_comprehensive(minimal_design_ir)
        assert score_result.power_integrity > 50
        assert score_result.section_details["power"]["bulk_caps"] > 0

    def test_power_score_high_with_regulators(self, detailed_design_ir):
        """Complex design with regulator and bulk caps scores high."""
        score_result = score_design_comprehensive(detailed_design_ir)
        assert score_result.power_integrity >= 70
        assert score_result.section_details["power"]["regulators"] > 0

    def test_power_gaps_reported(self, minimal_design_ir):
        """Power gaps are reported in details."""
        score_result = score_design_comprehensive(minimal_design_ir)
        power_details = score_result.section_details["power"]
        assert "power_gaps" in power_details


class TestSignalIntegrityScoring:
    """Test signal integrity scoring."""

    def test_signal_score_with_pullups(self, minimal_design_ir):
        """Score improves with pull-up resistors."""
        score_result = score_design_comprehensive(minimal_design_ir)
        assert score_result.signal_integrity >= 60
        assert score_result.section_details["signal"]["pullup_resistors"] > 0

    def test_signal_score_with_interfaces(self, detailed_design_ir):
        """Score improves with high-speed interfaces."""
        score_result = score_design_comprehensive(detailed_design_ir)
        assert score_result.signal_integrity >= 60
        # USB or differential pair detection
        assert (
            score_result.section_details["signal"]["differential_indicators"] > 0 or score_result.signal_integrity > 60
        )


class TestPlacementQualityScoring:
    """Test placement quality scoring."""

    def test_placement_score_with_references(self, minimal_design_ir):
        """Score improves with component references."""
        score_result = score_design_comprehensive(minimal_design_ir)
        assert score_result.placement_quality >= 60
        assert score_result.section_details["placement"]["total_components"] > 0

    def test_placement_constraints_count(self, detailed_design_ir):
        """Placement constraints are counted."""
        score_result = score_design_comprehensive(detailed_design_ir)
        placement_details = score_result.section_details["placement"]
        # Should count thermal_constraints from PCB constraints
        assert "thermal_constraints" in placement_details


class TestThermalScoring:
    """Test thermal design scoring."""

    def test_thermal_score_baseline(self, minimal_design_ir):
        """Thermal score provides baseline."""
        score_result = score_design_comprehensive(minimal_design_ir)
        assert 0 <= score_result.thermal <= 100

    def test_thermal_score_with_operating_range(self, detailed_design_ir):
        """Score rewards specified operating temperature."""
        score_result = score_design_comprehensive(detailed_design_ir)
        thermal_details = score_result.section_details["thermal"]
        # Should get bonus points for operating_temp in metadata
        assert score_result.thermal >= 70


class TestManufacturingScoring:
    """Test manufacturing readiness scoring."""

    def test_mfg_score_with_mpn(self, minimal_design_ir):
        """Score improves with MPN coverage."""
        score_result = score_design_comprehensive(minimal_design_ir)
        mfg_details = score_result.section_details["mfg"]
        assert mfg_details["components_with_mpn"] > 0
        assert score_result.manufacturing >= 60

    def test_mfg_score_with_substitutions(self, detailed_design_ir):
        """Score rewards sourcing alternatives."""
        score_result = score_design_comprehensive(detailed_design_ir)
        mfg_details = score_result.section_details["mfg"]
        assert mfg_details["substitutions"] > 0
        assert score_result.manufacturing >= 70


class TestComprehensiveScoring:
    """Test overall comprehensive scoring."""

    def test_comprehensive_score_minimal(self, minimal_design_ir):
        """Comprehensive score produces all 5 dimensions."""
        score_result = score_design_comprehensive(minimal_design_ir)
        assert isinstance(score_result, DetailedElectricalQualityScore)
        assert score_result.power_integrity > 0
        assert score_result.signal_integrity > 0
        assert score_result.placement_quality > 0
        assert score_result.thermal > 0
        assert score_result.manufacturing > 0
        assert 0 <= score_result.overall <= 100
        assert score_result.grade in "ABCDF"

    def test_comprehensive_score_detailed(self, detailed_design_ir):
        """Detailed design produces proportionally higher scores."""
        score_result = score_design_comprehensive(detailed_design_ir)
        # More complete design should score higher overall
        assert score_result.overall >= score_design_comprehensive(DesignIR()).overall

    def test_overall_is_weighted_average(self, minimal_design_ir):
        """Overall score is weighted average of 5 dimensions."""
        score_result = score_design_comprehensive(minimal_design_ir)
        expected = (
            score_result.power_integrity * 0.2
            + score_result.signal_integrity * 0.2
            + score_result.placement_quality * 0.2
            + score_result.thermal * 0.2
            + score_result.manufacturing * 0.2
        )
        assert abs(score_result.overall - expected) < 0.1

    def test_grade_mapping(self, minimal_design_ir):
        """Grade letter is correctly mapped from overall score."""
        score_result = score_design_comprehensive(minimal_design_ir)
        if score_result.overall >= 90:
            assert score_result.grade == "A"
        elif score_result.overall >= 80:
            assert score_result.grade == "B"
        elif score_result.overall >= 70:
            assert score_result.grade == "C"
        elif score_result.overall >= 60:
            assert score_result.grade == "D"
        else:
            assert score_result.grade == "F"

    def test_summary_text_generation(self, minimal_design_ir):
        """Summary text is generated properly."""
        score_result = score_design_comprehensive(minimal_design_ir)
        summary = score_result.summary_with_gaps()
        assert "Design Score:" in summary
        assert "Section Breakdown:" in summary
        assert "Power Integrity:" in summary
        assert "Signal Integrity:" in summary
