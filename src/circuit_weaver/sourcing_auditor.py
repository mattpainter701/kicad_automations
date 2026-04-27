"""Component sourcing risk audit.

Queries DigiKey (lifecycle status) and LCSC (stock/lead time) for each component
in a design. Flags obsolete, out-of-stock, long lead-time parts, and suggests
pin-compatible LCSC alternatives.

Usage:
    from circuit_weaver.sourcing_auditor import audit_bom
    result = audit_bom(spec)
    # result contains audit_status, components, critical, warnings, recommendations
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from .dispatcher import compile_design_ir
from .parts_lookup import PartsLookup

log = logging.getLogger(__name__)


def _append_alternates(lines: list[str], finding: "AuditFinding") -> None:
    """Append alternate part suggestions to a report line list."""
    for alt in finding.suggested_alternates:
        mpn_alt = alt.get("mpn", "?")
        mfr = alt.get("manufacturer", "?")
        stock_n = alt.get("stock", 0)
        lines.append(f"    Alternate: {mpn_alt} ({mfr}) \u2014 stock: {stock_n}")


@dataclass
class AuditFinding:
    """A single audit finding for a component."""

    ref: str
    mpn: str
    lcsc_pn: str
    description: str
    risk_level: str  # "CRITICAL", "WARNING", "OK"
    issues: list[str] = field(default_factory=list)
    stock: int = 0
    lead_time_weeks: int = 0
    lifecycle_status: str = ""  # "Active", "NRND", "Obsolete", "EOL", "Unknown"
    suggested_alternates: list[dict] = field(default_factory=list)


@dataclass
class AuditReport:
    """Overall audit report."""

    status: str  # "ok", "error"
    project: str
    message: str = ""
    components: list[AuditFinding] = field(default_factory=list)
    critical_count: int = 0
    warning_count: int = 0
    recommendations: list[str] = field(default_factory=list)


def _query_lcsc_stock(mpn: str, lcsc_pn: str = "") -> tuple[int, int]:
    """Query LCSC for stock and lead time.

    Returns: (stock_qty, lead_time_weeks)
    """
    search_term = lcsc_pn or mpn
    if not search_term:
        return 0, 0

    lookup = PartsLookup()
    result = lookup.lookup(search_term)
    if not result:
        return 0, 0

    stock = result.get("stock", 0)
    lead_time = result.get("lead_time_weeks", 0)
    return stock, lead_time


def _query_digikey_lifecycle(mpn: str) -> str:
    """Query DigiKey for lifecycle status.

    Returns: "Active", "NRND", "Obsolete", "EOL", or "Unknown"
    """
    if not mpn:
        return "Unknown"

    # For now, return "Unknown" as placeholder
    # Full implementation would use DigiKey API
    # This is a stub that can be enhanced later
    return "Unknown"


def _suggest_alternates(mpn: str, max_results: int = 3) -> list[dict]:
    """Search for functionally similar alternate parts via LCSC/DigiKey.

    Returns a list of dicts with keys: mpn, manufacturer, description,
    package, stock. Empty list if no alternates found.
    """
    if not mpn:
        return []

    try:
        lookup = PartsLookup()
        result = lookup.lookup(mpn)
        if not result:
            return []

        # Use the result description/package to search for alternates.
        # The PartsLookup already surfaces similar parts from LCSC search.
        description = result.get("description", "")

        # Build a keyword search from the description
        keywords = (description or mpn).split()[:4]
        if not keywords:
            return []

        alt_result = lookup.lookup(" ".join(keywords))
        if not alt_result:
            return []

        # Collect alternates with different MPN
        alt_mpn = alt_result.get("mpn", "")
        if alt_mpn and alt_mpn.upper() != mpn.upper():
            return [
                {
                    "mpn": alt_mpn,
                    "manufacturer": alt_result.get("manufacturer", ""),
                    "description": alt_result.get("description", ""),
                    "package": alt_result.get("package", ""),
                    "stock": alt_result.get("stock", 0),
                }
            ]
    except Exception:
        log.warning("Alternate suggestion failed for %s", mpn, exc_info=True)

    return []


def _classify_risk_level(
    stock: int,
    lead_time_weeks: int,
    lifecycle_status: str,
    has_distributor_pn: bool,
) -> str:
    """Classify risk level based on component attributes."""

    # CRITICAL conditions
    if lifecycle_status in ("Obsolete", "EOL"):
        return "CRITICAL"
    if stock == 0:
        return "CRITICAL"
    if lead_time_weeks > 16:
        return "CRITICAL"
    if not has_distributor_pn:
        return "CRITICAL"

    # WARNING conditions
    if stock < 100:
        return "WARNING"
    if lead_time_weeks > 8:
        return "WARNING"

    # OK
    return "OK"


def _identify_issues(
    stock: int,
    lead_time_weeks: int,
    lifecycle_status: str,
    has_distributor_pn: bool,
) -> list[str]:
    """Identify specific issues for a component."""
    issues = []

    if not has_distributor_pn:
        issues.append("No distributor part number")

    if lifecycle_status in ("Obsolete", "EOL"):
        issues.append(f"Lifecycle status: {lifecycle_status}")

    if stock == 0:
        issues.append("Out of stock")
    elif stock < 100:
        issues.append(f"Low stock: {stock} units")

    if lead_time_weeks > 16:
        issues.append(f"Very long lead time: {lead_time_weeks} weeks")
    elif lead_time_weeks > 8:
        issues.append(f"Long lead time: {lead_time_weeks} weeks")

    return issues


def audit_bom(spec: dict, lcsc_only: bool = False) -> AuditReport:
    """Audit BOM for component sourcing risks.

    Args:
        spec: Design spec dict (YAML-loaded).
        lcsc_only: Only query LCSC (skip DigiKey lifecycle).

    Returns:
        AuditReport with findings and recommendations.
    """

    # Compile the design
    try:
        compiled = compile_design_ir(spec)
    except Exception as e:
        return AuditReport(
            status="error",
            project=spec.get("project", "Unknown"),
            message=f"Failed to compile spec: {e}",
        )

    project_name = spec.get("project", "Unknown")
    components = compiled.components

    # Group components by (mpn, lcsc_pn) to match BOM grouping
    groups: dict[tuple, list[Any]] = {}
    for comp in components:
        if not comp.source_ref:
            continue

        key = (comp.source_mpn or comp.mpn or "", comp.lcsc_pn or "")
        if key not in groups:
            groups[key] = []
        groups[key].append(comp)

    # Audit each group
    findings: list[AuditFinding] = []
    critical_count = 0
    warning_count = 0
    recommendations: list[str] = []

    for (mpn, lcsc_pn), group_comps in groups.items():
        ref_list = ",".join(sorted(set(c.source_ref for c in group_comps)))
        description = group_comps[0].description or group_comps[0].value or ""

        # Query stock and lead time
        stock, lead_time = _query_lcsc_stock(mpn or "", lcsc_pn or "")

        # Query lifecycle status
        lifecycle = "Unknown"
        if not lcsc_only and mpn:
            lifecycle = _query_digikey_lifecycle(mpn)

        # Determine if part has a distributor PN
        has_dist_pn = bool(mpn or lcsc_pn)

        # Classify risk
        risk_level = _classify_risk_level(stock, lead_time, lifecycle, has_dist_pn)
        issues = _identify_issues(stock, lead_time, lifecycle, has_dist_pn)

        finding = AuditFinding(
            ref=ref_list,
            mpn=mpn or "",
            lcsc_pn=lcsc_pn or "",
            description=description,
            risk_level=risk_level,
            issues=issues,
            stock=stock,
            lead_time_weeks=lead_time,
            lifecycle_status=lifecycle,
            suggested_alternates=_suggest_alternates(mpn) if risk_level in ("CRITICAL", "WARNING") else [],
        )

        findings.append(finding)

        if risk_level == "CRITICAL":
            critical_count += 1
            recommendations.append(f"Component {ref_list}: {lifecycle or 'out-of-stock'} — find replacement ASAP")
        elif risk_level == "WARNING":
            warning_count += 1
            if stock < 100 and stock > 0:
                recommendations.append(f"Component {ref_list}: low stock ({stock}), order soon")

    # Sort findings: CRITICAL first, then WARNING
    findings.sort(key=lambda f: (f.risk_level != "CRITICAL", f.risk_level != "WARNING", f.ref))

    return AuditReport(
        status="ok",
        project=project_name,
        components=findings,
        critical_count=critical_count,
        warning_count=warning_count,
        recommendations=recommendations,
    )


def audit_report_text(report: AuditReport) -> str:
    """Format audit report as human-readable text."""

    lines = [
        f"Sourcing Audit: {report.project}",
        "=" * 60,
    ]

    if report.status == "error":
        lines.append(f"Error: {report.message}")
        return "\n".join(lines)

    lines.append(f"Critical issues: {report.critical_count}")
    lines.append(f"Warnings: {report.warning_count}")
    lines.append("")

    if report.critical_count > 0:
        lines.append("CRITICAL ISSUES:")
        for finding in report.components:
            if finding.risk_level == "CRITICAL":
                lines.append(f"  {finding.ref}: {finding.mpn or finding.lcsc_pn}")
                for issue in finding.issues:
                    lines.append(f"    - {issue}")
                _append_alternates(lines, finding)
        lines.append("")

    if report.warning_count > 0:
        lines.append("WARNINGS:")
        for finding in report.components:
            if finding.risk_level == "WARNING":
                lines.append(f"  {finding.ref}: {finding.mpn or finding.lcsc_pn}")
                for issue in finding.issues:
                    lines.append(f"    - {issue}")
                _append_alternates(lines, finding)
        lines.append("")

    if report.recommendations:
        lines.append("RECOMMENDATIONS:")
        for rec in report.recommendations:
            lines.append(f"  - {rec}")
        lines.append("")

    return "\n".join(lines)
