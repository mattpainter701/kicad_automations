"""Tests for component sourcing auditor."""

from __future__ import annotations

from unittest.mock import patch

from circuit_weaver.sourcing_auditor import (
    AuditFinding,
    AuditReport,
    _classify_risk_level,
    _identify_issues,
    _suggest_alternates,
    audit_bom,
    audit_report_text,
)


class TestRiskClassification:
    """Test risk level classification logic."""

    def test_critical_obsolete(self):
        """Obsolete parts are CRITICAL."""
        assert _classify_risk_level(100, 4, "Obsolete", True) == "CRITICAL"

    def test_critical_eol(self):
        """EOL parts are CRITICAL."""
        assert _classify_risk_level(100, 4, "EOL", True) == "CRITICAL"

    def test_critical_out_of_stock(self):
        """Out-of-stock parts are CRITICAL."""
        assert _classify_risk_level(0, 4, "Active", True) == "CRITICAL"

    def test_critical_long_lead_time(self):
        """Lead time > 16 weeks is CRITICAL."""
        assert _classify_risk_level(100, 20, "Active", True) == "CRITICAL"

    def test_critical_no_distributor_pn(self):
        """Parts without distributor PN are CRITICAL."""
        assert _classify_risk_level(100, 4, "Active", False) == "CRITICAL"

    def test_warning_low_stock(self):
        """Stock < 100 is WARNING."""
        assert _classify_risk_level(50, 4, "Active", True) == "WARNING"

    def test_warning_long_lead_time(self):
        """Lead time 8-16 weeks is WARNING."""
        assert _classify_risk_level(100, 12, "Active", True) == "WARNING"

    def test_ok_active(self):
        """Active part with good stock and lead time is OK."""
        assert _classify_risk_level(500, 4, "Active", True) == "OK"


class TestIssueIdentification:
    """Test issue identification logic."""

    def test_issue_out_of_stock(self):
        """Out-of-stock should be flagged."""
        issues = _identify_issues(0, 4, "Active", True)
        assert "Out of stock" in issues

    def test_issue_low_stock(self):
        """Low stock should be flagged."""
        issues = _identify_issues(50, 4, "Active", True)
        assert any("Low stock" in i and "50" in i for i in issues)

    def test_issue_long_lead_time(self):
        """Long lead time should be flagged."""
        issues = _identify_issues(100, 20, "Active", True)
        assert any("lead time" in i.lower() and "20" in i for i in issues)

    def test_issue_obsolete(self):
        """Obsolete status should be flagged."""
        issues = _identify_issues(100, 4, "Obsolete", True)
        assert any("Obsolete" in i for i in issues)

    def test_issue_no_distributor_pn(self):
        """Missing distributor PN should be flagged."""
        issues = _identify_issues(100, 4, "Active", False)
        assert "No distributor part number" in issues


class TestAuditReport:
    """Test audit report generation."""

    def test_audit_report_text_critical(self):
        """Report should include CRITICAL section."""
        finding = AuditFinding(
            ref="U1",
            mpn="AP62300",
            lcsc_pn="C460320",
            description="Buck converter",
            risk_level="CRITICAL",
            issues=["Out of stock"],
            stock=0,
        )
        report = AuditReport(
            status="ok",
            project="Test",
            components=[finding],
            critical_count=1,
        )
        text = audit_report_text(report)
        assert "CRITICAL ISSUES" in text
        assert "U1" in text

    def test_audit_report_text_warning(self):
        """Report should include WARNINGS section."""
        finding = AuditFinding(
            ref="R1",
            mpn="RC0603",
            lcsc_pn="C98765",
            description="Resistor",
            risk_level="WARNING",
            issues=["Low stock: 50 units"],
            stock=50,
        )
        report = AuditReport(
            status="ok",
            project="Test",
            components=[finding],
            warning_count=1,
        )
        text = audit_report_text(report)
        assert "WARNINGS" in text
        assert "R1" in text

    def test_audit_report_text_includes_alternates(self):
        """Report should include alternate suggestions for risky parts."""
        finding = AuditFinding(
            ref="U1",
            mpn="OLDPART",
            lcsc_pn="C1",
            description="Regulator",
            risk_level="CRITICAL",
            issues=["Out of stock"],
            suggested_alternates=[{"mpn": "NEWPART", "manufacturer": "Acme", "stock": 1234}],
        )
        report = AuditReport(status="ok", project="Test", components=[finding], critical_count=1)

        text = audit_report_text(report)

        assert "Alternate: NEWPART" in text
        assert "stock: 1234" in text

    def test_audit_report_text_recommendations(self):
        """Report should include recommendations."""
        report = AuditReport(
            status="ok",
            project="Test",
            recommendations=["Use C123456 instead of C789012"],
        )
        text = audit_report_text(report)
        assert "RECOMMENDATIONS" in text
        assert "C123456" in text


class TestAuditBOM:
    """Test BOM audit integration."""

    def test_audit_bom_missing_spec(self):
        """Audit should handle missing spec gracefully."""
        result = audit_bom({})
        assert result.status in ("ok", "error")
        assert result.project == "Unknown"

    def test_audit_bom_invalid_spec(self):
        """Audit should handle invalid spec gracefully."""
        result = audit_bom({"invalid": "spec"})
        assert result.status == "error" or result.status == "ok"

    def test_audit_bom_adds_alternates_for_warning_parts(self):
        """Risky findings should carry alternate suggestions."""
        from types import SimpleNamespace

        from circuit_weaver.component_db import ComponentDef

        comp = ComponentDef(
            mpn="AP2112K-3.3",
            source_ref="U1",
            description="LDO regulator",
            lcsc_pn="C123",
        )
        spec = {"project": "test"}
        with (
            patch(
                "circuit_weaver.sourcing_auditor.compile_design_ir",
                return_value=SimpleNamespace(components=[comp]),
            ),
            patch("circuit_weaver.sourcing_auditor._query_lcsc_stock", return_value=(50, 4)),
            patch("circuit_weaver.sourcing_auditor._query_digikey_lifecycle", return_value="Active"),
            patch("circuit_weaver.sourcing_auditor._suggest_alternates", return_value=[{"mpn": "ALT1"}]),
        ):
            report = audit_bom(spec)

        assert report.status == "ok"
        warning_findings = [item for item in report.components if item.risk_level == "WARNING"]
        assert warning_findings
        assert warning_findings[0].suggested_alternates == [{"mpn": "ALT1"}]


class TestAlternateSuggestions:
    """Test alternate-suggestion lookup behavior."""

    def test_suggest_alternates_returns_empty_without_mpn(self):
        assert _suggest_alternates("") == []

    def test_suggest_alternates_uses_description_keywords(self):
        lookup_results = [
            {"mpn": "OLD", "description": "3.3V LDO regulator SOT-23", "stock": 0},
            {
                "mpn": "NEW",
                "manufacturer": "Acme",
                "description": "3.3V LDO regulator SOT-23",
                "package": "SOT-23",
                "stock": 5000,
            },
        ]
        with patch("circuit_weaver.sourcing_auditor.PartsLookup") as mock_lookup:
            mock_lookup.return_value.lookup.side_effect = lookup_results

            alternates = _suggest_alternates("OLD")

        assert alternates == [
            {
                "mpn": "NEW",
                "manufacturer": "Acme",
                "description": "3.3V LDO regulator SOT-23",
                "package": "SOT-23",
                "stock": 5000,
            }
        ]

    def test_suggest_alternates_filters_same_mpn(self):
        with patch("circuit_weaver.sourcing_auditor.PartsLookup") as mock_lookup:
            mock_lookup.return_value.lookup.side_effect = [
                {"mpn": "OLD", "description": "LDO regulator"},
                {"mpn": "old", "description": "same part"},
            ]

            assert _suggest_alternates("OLD") == []


class TestFindingDataclass:
    """Test AuditFinding dataclass."""

    def test_finding_creation(self):
        """AuditFinding should be creatable with basic fields."""
        finding = AuditFinding(
            ref="U1",
            mpn="AP62300",
            lcsc_pn="C460320",
            description="Boost converter",
            risk_level="CRITICAL",
        )
        assert finding.ref == "U1"
        assert finding.mpn == "AP62300"
        assert finding.risk_level == "CRITICAL"

    def test_finding_default_fields(self):
        """AuditFinding should have sensible defaults."""
        finding = AuditFinding(
            ref="R1",
            mpn="10k",
            lcsc_pn="",
            description="Resistor",
            risk_level="OK",
        )
        assert finding.stock == 0
        assert finding.lead_time_weeks == 0
        assert finding.lifecycle_status == ""
        assert finding.suggested_alternates == []
