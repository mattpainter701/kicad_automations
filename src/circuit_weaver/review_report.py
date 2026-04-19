"""Interactive HTML design review report generator.

Produces a comprehensive, self-contained HTML report with:
- Design summary card and checklist
- DFM violations analysis
- Component BOM table
- Design quality scoring breakdown (5 dimensions)
- Power tree visualization
- Actionable recommendations
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from .design_docs import _generate_bom_table, _generate_power_budget
from .design_ir import DesignBlock, DesignIR
from .design_scorer import score_design_comprehensive
from .dfm_checker import check_dfm


def _html_escape(s: str) -> str:
    """Escape HTML special characters."""
    return (
        s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;").replace("'", "&#39;")
    )


def _format_score(score: float) -> str:
    """Format score as colored badge."""
    if score >= 90:
        color = "#2ecc71"  # green
    elif score >= 80:
        color = "#27ae60"  # dark green
    elif score >= 70:
        color = "#f39c12"  # orange
    elif score >= 60:
        color = "#e67e22"  # dark orange
    else:
        color = "#e74c3c"  # red

    return f'<span style="color: {color}; font-weight: bold;">{score:.1f}</span>'


def generate_review_report_html(
    design_ir: DesignIR,
    output_path: str | Path,
    kicad_pcb_path: str | Path | None = None,
    erc_result: Any = None,
    log_entries: list[dict] | None = None,
) -> Path:
    """Generate comprehensive HTML design review report.

    Args:
        design_ir: Compiled DesignIR object
        output_path: Path to write HTML report
        kicad_pcb_path: Optional path to .kicad_pcb file for DFM analysis

    Returns:
        Path to generated HTML file
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Collect all data
    metadata = design_ir.metadata or {}
    project_name = metadata.get("project", "Design Project")
    version = metadata.get("version", "1.0")
    description = metadata.get("description", "")
    created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Design scoring
    score_result = score_design_comprehensive(design_ir)

    # BOM extraction
    bom_table = _generate_bom_table(design_ir)
    power_budget = _generate_power_budget(design_ir)

    # DFM violations (if PCB file provided)
    dfm_violations = []
    if kicad_pcb_path:
        try:
            dfm_violations = check_dfm(str(kicad_pcb_path), profile="jlcpcb")
        except Exception:
            dfm_violations = []

    # Sort violations by severity
    severity_order = {"critical": 0, "warning": 1}
    dfm_violations.sort(
        key=lambda v: (
            severity_order.get(v.severity, 2),
            v.type,
        )
    )

    # Build HTML
    html_parts = [
        "<!DOCTYPE html>",
        '<html lang="en">',
        "<head>",
        '  <meta charset="UTF-8">',
        '  <meta name="viewport" content="width=device-width, initial-scale=1.0">',
        f"  <title>{_html_escape(project_name)} Design Review Report</title>",
        _generate_css(),
        "</head>",
        "<body>",
        '  <div class="container">',
        _generate_header(project_name, version, description, created_at, score_result),
        _generate_summary_card(project_name, version, score_result),
        _generate_checklist(),
        _generate_scoring_breakdown(score_result),
        _generate_erc_section(erc_result),
        _generate_rationale_section(design_ir, log_entries),
        _generate_dfm_section(dfm_violations),
        _generate_bom_section(bom_table),
        _generate_power_tree_section(power_budget),
        _generate_recommendations(score_result, dfm_violations),
        "  </div>",
        _generate_footer(),
        "</body>",
        "</html>",
    ]

    html_content = "\n".join(html_parts)
    output_path.write_text(html_content, encoding="utf-8")

    return output_path


def _generate_css() -> str:
    """Generate embedded CSS styles."""
    return """  <style>
    :root {
      --primary: #3498db;
      --success: #2ecc71;
      --warning: #f39c12;
      --danger: #e74c3c;
      --dark: #2c3e50;
      --light: #ecf0f1;
      --border: #bdc3c7;
    }

    * {
      margin: 0;
      padding: 0;
      box-sizing: border-box;
    }

    body {
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
      background: linear-gradient(135deg, #f5f7fa 0%, #c3cfe2 100%);
      color: var(--dark);
      line-height: 1.6;
    }

    .container {
      max-width: 1200px;
      margin: 0 auto;
      padding: 20px;
      background: white;
      box-shadow: 0 10px 40px rgba(0,0,0,0.1);
    }

    header {
      border-bottom: 3px solid var(--primary);
      padding-bottom: 20px;
      margin-bottom: 30px;
    }

    h1 {
      color: var(--primary);
      font-size: 2.5em;
      margin-bottom: 5px;
    }

    h2 {
      color: var(--dark);
      font-size: 1.8em;
      margin-top: 40px;
      margin-bottom: 15px;
      border-left: 4px solid var(--primary);
      padding-left: 15px;
    }

    h3 {
      color: var(--dark);
      font-size: 1.3em;
      margin-top: 20px;
      margin-bottom: 10px;
    }

    .summary-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
      gap: 15px;
      margin-bottom: 30px;
    }

    .card {
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 20px;
      background: #f9f9f9;
      box-shadow: 0 2px 8px rgba(0,0,0,0.05);
    }

    .card h3 {
      margin-top: 0;
      color: var(--primary);
    }

    .score-badge {
      display: inline-block;
      padding: 8px 16px;
      border-radius: 20px;
      background: var(--light);
      font-weight: bold;
      margin: 5px 5px 5px 0;
    }

    .checklist {
      background: #f0f8ff;
      padding: 20px;
      border-radius: 8px;
      margin: 15px 0;
    }

    .checklist label {
      display: block;
      margin: 10px 0;
      cursor: pointer;
    }

    .checklist input[type="checkbox"] {
      margin-right: 10px;
    }

    table {
      width: 100%;
      border-collapse: collapse;
      margin: 15px 0;
      background: white;
    }

    thead {
      background: var(--primary);
      color: white;
    }

    th, td {
      padding: 12px;
      text-align: left;
      border-bottom: 1px solid var(--border);
    }

    tbody tr:nth-child(even) {
      background: #f9f9f9;
    }

    tbody tr:hover {
      background: #f0f0f0;
    }

    .severity-critical {
      color: var(--danger);
      font-weight: bold;
    }

    .severity-warning {
      color: var(--warning);
      font-weight: bold;
    }

    .recommendation {
      background: #e8f4f8;
      border-left: 4px solid var(--primary);
      padding: 15px;
      margin: 10px 0;
      border-radius: 4px;
    }

    .chart-container {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
      gap: 20px;
      margin: 20px 0;
    }

    .score-breakdown {
      background: #f9f9f9;
      padding: 20px;
      border-radius: 8px;
      margin: 15px 0;
    }

    .score-bar {
      width: 100%;
      height: 30px;
      background: var(--light);
      border-radius: 5px;
      overflow: hidden;
      margin: 10px 0;
      position: relative;
    }

    .score-bar-fill {
      height: 100%;
      background: linear-gradient(90deg, var(--success), var(--primary));
      display: flex;
      align-items: center;
      justify-content: center;
      color: white;
      font-weight: bold;
      font-size: 0.9em;
    }

    .gap-warning {
      background: #fff3cd;
      border: 1px solid #ffc107;
      padding: 10px;
      border-radius: 4px;
      margin: 10px 0;
    }

    footer {
      border-top: 1px solid var(--border);
      padding-top: 20px;
      margin-top: 40px;
      text-align: center;
      color: #666;
      font-size: 0.9em;
    }

    @media print {
      body {
        background: white;
      }
      .container {
        box-shadow: none;
        max-width: 100%;
      }
      h2 {
        page-break-after: avoid;
      }
      table {
        page-break-inside: avoid;
      }
    }
  </style>"""


def _generate_header(
    project_name: str,
    version: str,
    description: str,
    created_at: str,
    score_result: Any,
) -> str:
    """Generate HTML header section."""
    return f"""  <header>
    <h1>{_html_escape(project_name)}</h1>
    <p><strong>Version:</strong> {_html_escape(version)} | <strong>Date:</strong> {created_at}</p>
    {f"<p><strong>Description:</strong> {_html_escape(description)}</p>" if description else ""}
    <p><strong>Overall Score:</strong> {_format_score(score_result.overall)} ({score_result.grade})</p>
  </header>"""


def _generate_summary_card(project_name: str, version: str, score_result: Any) -> str:
    """Generate summary card section."""
    return f"""  <section>
    <h2>Design Summary</h2>
    <div class="summary-grid">
      <div class="card">
        <h3>Overall Quality</h3>
        <p style="font-size: 2.5em; color: var(--primary);">{score_result.overall:.1f}
          <span style="font-size: 0.6em;">({score_result.grade})</span></p>
        <p>Composite score across all design dimensions</p>
      </div>
      <div class="card">
        <h3>Power Integrity</h3>
        <p>{_format_score(score_result.power_integrity)}</p>
        <small>Decoupling, bulk caps, regulator headroom</small>
      </div>
      <div class="card">
        <h3>Signal Integrity</h3>
        <p>{_format_score(score_result.signal_integrity)}</p>
        <small>Termination, differential pairs</small>
      </div>
      <div class="card">
        <h3>Placement Quality</h3>
        <p>{_format_score(score_result.placement_quality)}</p>
        <small>Component organization, constraints</small>
      </div>
      <div class="card">
        <h3>Thermal Design</h3>
        <p>{_format_score(score_result.thermal)}</p>
        <small>Power dissipation, thermal analysis</small>
      </div>
      <div class="card">
        <h3>Manufacturing</h3>
        <p>{_format_score(score_result.manufacturing)}</p>
        <small>MPN coverage, sourcing, complexity</small>
      </div>
    </div>
  </section>"""


def _generate_checklist() -> str:
    """Generate pre-fabrication checklist."""
    items = [
        ("Design validation", "All validation checks passing"),
        ("DFM compliance", "No critical DFM violations"),
        ("BOM complete", "All components have MPNs"),
        ("Datasheets available", "All components documented"),
        ("Power budget verified", "Estimated current within limits"),
        ("Signal integrity", "Critical nets terminated/matched"),
        ("Thermal design", "Power dissipation acceptable"),
        ("Schematic review", "Layout and connectivity verified"),
    ]

    checklist_html = """  <section>
    <h2>Pre-Fabrication Checklist</h2>
    <div class="checklist">
"""
    for label, desc in items:
        checklist_html += f"""      <label>
        <input type="checkbox">
        <strong>{label}:</strong> <span>{desc}</span>
      </label>
"""
    checklist_html += """    </div>
  </section>"""

    return checklist_html


def _generate_scoring_breakdown(score_result: Any) -> str:
    """Generate detailed scoring breakdown."""
    sections = [
        ("Power Integrity", score_result.power_integrity, score_result.section_details["power"]["power_gaps"]),
        ("Signal Integrity", score_result.signal_integrity, score_result.section_details["signal"]["signal_gaps"]),
        (
            "Placement Quality",
            score_result.placement_quality,
            score_result.section_details["placement"]["placement_gaps"],
        ),
        ("Thermal", score_result.thermal, score_result.section_details["thermal"]["thermal_gaps"]),
        ("Manufacturing", score_result.manufacturing, score_result.section_details["mfg"]["mfg_gaps"]),
    ]

    html = """  <section>
    <h2>Detailed Scoring Analysis</h2>
    <div class="score-breakdown">
"""

    for section_name, score, gaps in sections:
        color = "#2ecc71" if score >= 75 else "#e74c3c"
        html += f"""      <h3>{section_name}</h3>
      <div class="score-bar">
        <div class="score-bar-fill" style="width: {min(100, score)}%; background: {color};">
          {score:.1f}
        </div>
      </div>
"""
        if gaps != "None":
            html += f"""      <div class="gap-warning">
        <strong>Gap:</strong> {_html_escape(gaps)}
      </div>
"""

    html += """    </div>
  </section>"""

    return html


def _generate_erc_section(erc_result: Any) -> str:
    """Generate ERC status section.

    Shows a green badge when ERC is clean, a red error list when violations
    exist, and a neutral notice when ERC was skipped or not run.
    """
    if erc_result is None:
        return """  <section>
    <h2>ERC Status</h2>
    <p style="color: gray;">ERC: not run (no schematic path provided)</p>
  </section>"""

    # Accept both ErcResult objects and plain dicts (from generate_artifacts JSON)
    if isinstance(erc_result, dict):
        status = erc_result.get("status", "skipped")
        errors = erc_result.get("errors", 0)
        warnings = erc_result.get("warnings", 0)
        skip_reason = erc_result.get("skip_reason", "")
        violations = erc_result.get("violations", [])
    else:
        status = erc_result.status
        errors = erc_result.errors
        warnings = erc_result.warnings
        skip_reason = erc_result.skip_reason
        violations = [
            {"type": v.type, "description": v.description, "severity": v.severity} for v in erc_result.violations
        ]

    if status == "skipped":
        reason_html = _html_escape(skip_reason) if skip_reason else "KiCad CLI unavailable"
        return f"""  <section>
    <h2>ERC Status</h2>
    <p style="color: gray;">ERC: not run ({reason_html})</p>
  </section>"""

    if status == "failed":
        reason_html = _html_escape(skip_reason) if skip_reason else "unknown error"
        return f"""  <section>
    <h2>ERC Status</h2>
    <p style="color: orange; font-weight: bold;">⚠ ERC failed: {reason_html}</p>
  </section>"""

    # status == "ok"
    if errors == 0 and warnings == 0:
        return """  <section>
    <h2>ERC Status</h2>
    <p style="color: green; font-weight: bold;">✓ ERC: 0 errors, 0 warnings</p>
  </section>"""

    badge_color = "red" if errors > 0 else "orange"
    badge_text = f"✗ ERC: {errors} error(s), {warnings} warning(s)"
    rows = ""
    for v in violations:
        sev = v.get("severity", "warning") if isinstance(v, dict) else v.severity
        vtype = v.get("type", "") if isinstance(v, dict) else v.type
        desc = v.get("description", "") if isinstance(v, dict) else v.description
        row_class = "severity-critical" if sev == "error" else "severity-warning"
        rows += f"""        <tr>
          <td class="{row_class}">{sev.upper()}</td>
          <td>{_html_escape(vtype)}</td>
          <td>{_html_escape(desc)}</td>
        </tr>
"""

    return f"""  <section>
    <h2>ERC Status</h2>
    <p style="color: {badge_color}; font-weight: bold;">{badge_text}</p>
    <table>
      <thead>
        <tr><th>Severity</th><th>Type</th><th>Description</th></tr>
      </thead>
      <tbody>
{rows}      </tbody>
    </table>
  </section>"""


def _generate_dfm_section(dfm_violations: list) -> str:
    """Generate DFM violations section."""
    if not dfm_violations:
        return """  <section>
    <h2>DFM Analysis</h2>
    <p style="color: green; font-weight: bold;">✓ No DFM violations detected</p>
  </section>"""

    html = """  <section>
    <h2>DFM Violations</h2>
    <table>
      <thead>
        <tr>
          <th>Severity</th>
          <th>Type</th>
          <th>Location</th>
          <th>Actual</th>
          <th>Minimum</th>
          <th>Suggestion</th>
        </tr>
      </thead>
      <tbody>
"""

    for v in dfm_violations:
        severity_class = f"severity-{v.severity}"
        html += f"""        <tr>
          <td class="{severity_class}">{v.severity.upper()}</td>
          <td>{_html_escape(v.type)}</td>
          <td>{_html_escape(v.location)}</td>
          <td>{v.actual if v.actual is not None else "N/A"}</td>
          <td>{v.minimum if v.minimum is not None else "N/A"}</td>
          <td>{_html_escape(v.suggestion or "")}</td>
        </tr>
"""

    html += """      </tbody>
    </table>
  </section>"""

    return html


def _generate_bom_section(bom_table: list) -> str:
    """Generate BOM table section."""
    if not bom_table:
        return """  <section>
    <h2>Component BOM</h2>
    <p>No components found.</p>
  </section>"""

    html = """  <section>
    <h2>Component Bill of Materials</h2>
    <table>
      <thead>
        <tr>
          <th>Reference</th>
          <th>Value</th>
          <th>Footprint</th>
          <th>MPN</th>
          <th>Manufacturer</th>
          <th>Category</th>
          <th>Qty</th>
        </tr>
      </thead>
      <tbody>
"""

    for item in bom_table:
        html += f"""        <tr>
          <td>{_html_escape(item.get("reference", ""))}</td>
          <td>{_html_escape(item.get("value", ""))}</td>
          <td>{_html_escape(item.get("footprint", ""))}</td>
          <td><code>{_html_escape(item.get("mpn", ""))}</code></td>
          <td>{_html_escape(item.get("manufacturer", ""))}</td>
          <td>{_html_escape(item.get("category", ""))}</td>
          <td>{item.get("quantity", 1)}</td>
        </tr>
"""

    html += """      </tbody>
    </table>
  </section>"""

    return html


def _generate_power_tree_section(power_budget: list) -> str:
    """Generate power tree section."""
    if not power_budget:
        return """  <section>
    <h2>Power Distribution</h2>
    <p>No power rails identified.</p>
  </section>"""

    html = """  <section>
    <h2>Power Distribution Tree</h2>
    <table>
      <thead>
        <tr>
          <th>Rail</th>
          <th>Voltage (V)</th>
          <th>Current (mA)</th>
          <th>Power (W)</th>
        </tr>
      </thead>
      <tbody>
"""

    for rail in power_budget:
        html += f"""        <tr>
          <td><strong>{_html_escape(rail.get("rail", ""))}</strong></td>
          <td>{rail.get("voltage", 0):.2f}</td>
          <td>{rail.get("current_ma", 0):.1f}</td>
          <td>{rail.get("power_w", 0):.3f}</td>
        </tr>
"""

    html += """      </tbody>
    </table>
  </section>"""

    return html


def _generate_recommendations(score_result: Any, dfm_violations: list) -> str:
    """Generate actionable recommendations."""
    html = """  <section>
    <h2>Recommendations & Next Steps</h2>
"""

    recommendations = []

    # Score-based recommendations
    if score_result.power_integrity < 75:
        msg = (
            "Add bulk capacitors (10-100µF) on main power rails and "
            "increase decoupling capacitor coverage on all IC power pins."
        )
        recommendations.append(msg)
    if score_result.signal_integrity < 75:
        msg = (
            "Add pull-up resistors on I2C/SPI buses and verify "
            "differential pair length matching for high-speed signals."
        )
        recommendations.append(msg)
    if score_result.placement_quality < 75:
        recommendations.append(
            "Improve placement organization and add explicit thermal/placement constraints for critical components."
        )
    if score_result.thermal < 75:
        recommendations.append(
            "Conduct thermal analysis for high-power components and add thermal vias under power devices if needed."
        )
    if score_result.manufacturing < 75:
        recommendations.append(
            "Ensure all components have MPN assignments and verify part availability at target production volume."
        )

    # DFM-based recommendations
    critical_dfm = [v for v in dfm_violations if v.severity == "critical"]
    if critical_dfm:
        rec_list = "; ".join(f"{v.type} on {v.location}" for v in critical_dfm[:3])
        recommendations.append(f"Resolve critical DFM violations: {rec_list}")

    if recommendations:
        html += """    <ol>
"""
        for rec in recommendations:
            html += f"""      <li class="recommendation">{_html_escape(rec)}</li>
"""
        html += """    </ol>
"""
    else:
        html += """    <p style="color: green; font-weight: bold;">✓ Design is well-prepared for fabrication</p>
"""

    html += """  </section>"""

    return html


def _extract_component_rationale(block: DesignBlock, log_entries: list[dict] | None = None) -> dict:
    """Extract selection rationale for a single design block.

    Returns a dict with keys: ref, ic, why_selected, reference_design, key_specs, fallback.
    """
    rationale: dict = {
        "ref": block.ref or block.id,
        "ic": block.ic or block.mpn or "",
        "why_selected": block.description or "",
        "reference_design": str(block.params.get("reference_design", "")) if block.params else "",
        "key_specs": [],
        "fallback": False,
    }

    # Pull key electrical specs from params
    _SPEC_KEYS = ("voltage", "vin", "vout", "current", "iout", "power", "frequency", "speed")
    for key in _SPEC_KEYS:
        if block.params and key in block.params:
            rationale["key_specs"].append(f"{key}: {block.params[key]}")

    # Supplement from design.log entries when available
    if log_entries:
        for entry in log_entries:
            etype = entry.get("type", "")
            if etype == "wizard_step" and not rationale["why_selected"]:
                desc = entry.get("description", "")
                user_input = entry.get("user_input") or {}
                ref_lower = (block.ref or "").lower()
                if ref_lower and any(ref_lower in str(v).lower() for v in user_input.values()):
                    rationale["why_selected"] = f"Wizard step {entry.get('step', '?')}: {desc}"
            elif etype == "research" and block.ic:
                phase = entry.get("phase", "")
                if block.ic.lower() in phase.lower() and not rationale["why_selected"]:
                    rationale["why_selected"] = f"Research-selected ({phase})"

    if not rationale["why_selected"] and not rationale["key_specs"]:
        rationale["fallback"] = True

    return rationale


def _generate_rationale_section(design_ir: DesignIR, log_entries: list[dict] | None = None) -> str:
    """Generate the Component Selection Rationale HTML section.

    Shows, per IC/component block: why the component was selected, any reference
    design cited, and key electrical specs used in selection. Falls back to a
    "verify against datasheet" notice when no rationale is recorded.
    """
    ic_blocks = [b for b in design_ir.blocks if b.ic or b.template_type or b.kind == "component"]

    if not ic_blocks:
        return """  <section>
    <h2>Component Selection Rationale</h2>
    <p>No components found in this design.</p>
  </section>"""

    rows = ""
    for block in ic_blocks:
        r = _extract_component_rationale(block, log_entries)

        ref_html = _html_escape(r["ref"])
        ic_html = _html_escape(r["ic"])
        ref_design_html = _html_escape(r["reference_design"]) if r["reference_design"] else "—"
        specs_html = ", ".join(_html_escape(s) for s in r["key_specs"]) or "—"

        if r["fallback"]:
            why_html = (
                '<span style="color: gray; font-style: italic;">'
                "Selected via component registry — verify against datasheet"
                "</span>"
            )
        else:
            why_html = _html_escape(r["why_selected"])

        rows += f"""        <tr>
          <td><strong>{ref_html}</strong></td>
          <td><code>{ic_html}</code></td>
          <td>{why_html}</td>
          <td>{ref_design_html}</td>
          <td>{specs_html}</td>
        </tr>
"""

    return f"""  <section>
    <h2>Component Selection Rationale</h2>
    <table>
      <thead>
        <tr>
          <th>Reference</th>
          <th>Component</th>
          <th>Why Selected</th>
          <th>Reference Design</th>
          <th>Key Specs</th>
        </tr>
      </thead>
      <tbody>
{rows}      </tbody>
    </table>
  </section>"""


def _generate_footer() -> str:
    """Generate footer."""
    created = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    footer_note = "This report is a design review aid and should be reviewed by qualified engineers before fabrication."
    return f"""  <footer>
    <p>Generated by Circuit Weaver | {created}</p>
    <p style="font-size: 0.8em;">{footer_note}</p>
  </footer>"""
