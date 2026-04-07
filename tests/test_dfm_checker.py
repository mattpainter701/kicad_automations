"""Tests for DFM (Design for Manufacture) checker."""

from circuit_weaver.dfm_checker import (
    _DFM_PROFILES,
    DFMViolation,
    _parse_pcb_s_expr,
    check_dfm,
    dfm_report,
)


class TestDFMProfiles:
    """Test DFM profile definitions."""

    def test_jlcpcb_profile_exists(self):
        """JLCPCB profile should be defined."""
        assert "jlcpcb" in _DFM_PROFILES
        profile = _DFM_PROFILES["jlcpcb"]
        assert profile["trace_width_min"] == 0.127
        assert profile["via_diameter_min"] == 0.45

    def test_pcbway_profile_exists(self):
        """PCBWay profile should be defined."""
        assert "pcbway" in _DFM_PROFILES
        profile = _DFM_PROFILES["pcbway"]
        assert profile["trace_width_min"] == 0.1
        assert profile["via_diameter_min"] == 0.3


class TestPCBParsing:
    """Test PCB S-expression parsing."""

    def test_parse_empty_pcb(self):
        """Parse minimal PCB content."""
        content = "(kicad_pcb (version 20231120))"
        pcb = _parse_pcb_s_expr(content)
        assert pcb["nets"] == {}
        assert pcb["tracks"] == []
        assert pcb["vias"] == []

    def test_parse_nets(self):
        """Extract net names and numbers."""
        content = """
        (kicad_pcb (version 20231120)
            (net 0 "")
            (net 1 "GND")
            (net 2 "VDD_3V3")
        )
        """
        pcb = _parse_pcb_s_expr(content)
        assert pcb["nets"]["GND"] == 1
        assert pcb["nets"]["VDD_3V3"] == 2

    def test_parse_board_size(self):
        """Extract board dimensions."""
        content = "(kicad_pcb (size 100 80))"
        pcb = _parse_pcb_s_expr(content)
        assert pcb["board_width_mm"] == 100.0
        assert pcb["board_height_mm"] == 80.0


class TestDFMViolation:
    """Test DFMViolation data class."""

    def test_violation_creation(self):
        """Create a DFM violation."""
        v = DFMViolation(
            severity="critical",
            type="trace_width",
            location="net VDD_3V3",
            actual=0.1,
            minimum=0.127,
            message="Trace too narrow",
            suggestion="Increase trace width",
        )
        assert v.severity == "critical"
        assert v.type == "trace_width"

    def test_violation_to_dict(self):
        """Convert violation to dict."""
        v = DFMViolation(
            severity="warning",
            type="via_drill",
            location="Via 5",
            actual=0.15,
            minimum=0.2,
            message="Via drill too small",
        )
        d = v.to_dict()
        assert d["severity"] == "warning"
        assert d["actual"] == 0.15


class TestDFMReport:
    """Test DFM report generation."""

    def test_empty_report(self):
        """Report with no violations."""
        report = dfm_report([])
        assert "No DFM violations detected" in report

    def test_critical_violations_report(self):
        """Report with critical violations."""
        violations = [
            DFMViolation(
                severity="critical",
                type="trace_width",
                location="net signal",
                actual=0.1,
                minimum=0.127,
                message="Trace width violation",
                suggestion="Increase width",
            )
        ]
        report = dfm_report(violations)
        assert "CRITICAL" in report
        assert "TRACE_WIDTH" in report.upper()

    def test_warning_violations_report(self):
        """Report with warning violations."""
        violations = [
            DFMViolation(
                severity="warning",
                type="board_edge_clearance",
                location="Via 1",
                actual=None,
                minimum=0.3,
                message="Via near edge",
                suggestion="Move via away from edge",
            )
        ]
        report = dfm_report(violations)
        assert "WARNINGS" in report or "⚠️" in report


class TestCheckDFM:
    """Test full DFM check."""

    def test_check_dfm_missing_file(self, tmp_path):
        """Check nonexistent file."""
        violations = check_dfm(tmp_path / "missing.kicad_pcb")
        assert violations == []

    def test_check_dfm_empty_file(self, tmp_path):
        """Check empty PCB file."""
        pcb_file = tmp_path / "empty.kicad_pcb"
        pcb_file.write_text("(kicad_pcb (version 20231120))")
        violations = check_dfm(str(pcb_file), profile="jlcpcb")
        assert isinstance(violations, list)

    def test_check_dfm_with_custom_rules(self, tmp_path):
        """Check with custom DFM rules."""
        pcb_file = tmp_path / "test.kicad_pcb"
        pcb_file.write_text("(kicad_pcb (version 20231120))")
        custom = {"trace_width_min": 0.5}
        violations = check_dfm(str(pcb_file), custom_rules=custom)
        assert isinstance(violations, list)

    def test_check_dfm_profile_fallback(self, tmp_path):
        """Unknown profile should fall back to default."""
        pcb_file = tmp_path / "test.kicad_pcb"
        pcb_file.write_text("(kicad_pcb (version 20231120))")
        violations = check_dfm(str(pcb_file), profile="unknown_fab")
        # Should not raise, should return list
        assert isinstance(violations, list)
