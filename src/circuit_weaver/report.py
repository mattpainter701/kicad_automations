"""Design report generation for schematic engine output.

Generates a markdown report alongside schematics: power tree, BOM summary,
validation results, per-subcircuit design rationale, and component list.

Usage:
    from circuit_weaver.report import generate_report
    generate_report(components, validation_results, output_path, metadata)
"""

from __future__ import annotations

import datetime
from pathlib import Path

from .component_db import ComponentDef


def _power_tree_section(components: list[ComponentDef]) -> str:
    """Generate a text-based power tree from component power pin assignments."""
    lines = ["## Power Tree\n"]
    ground_nets = {"GND", "AGND", "DGND", "PGND", "GNDA"}

    # Collect all power rails and which components source/sink them
    rail_sources: dict[str, list[str]] = {}  # rail -> list of source refs
    rail_sinks: dict[str, list[str]] = {}  # rail -> list of sink refs

    for comp in components:
        ref = comp.source_ref or comp.mpn
        pin_types = {pin.number: pin.electrical_type for pin in comp.pins}
        output_nets = set()
        if comp.category == "power":
            for bc in comp.bypass_caps:
                if bc.pin.upper() in ("COUT", "OUT", "L"):
                    output_nets.add(bc.net)
            for strap in comp.straps:
                if "FB" in strap.pin.upper():
                    output_nets.add(strap.rail)

        for pin_num, net in comp.power_pins.items():
            if net in ground_nets:
                continue
            pin_type = pin_types.get(pin_num, "")
            if pin_type == "power_out" or (comp.category == "power" and net in output_nets):
                rail_sources.setdefault(net, [])
                if ref not in rail_sources[net]:
                    rail_sources[net].append(ref)
            else:
                rail_sinks.setdefault(net, [])
                if ref not in rail_sinks[net]:
                    rail_sinks[net].append(ref)

        # Bypass caps also indicate rail usage
        for bc in comp.bypass_caps:
            if bc.net not in ground_nets:
                rail_sinks.setdefault(bc.net, []).append(f"{ref}:{bc.pin}")

    if not rail_sources and not rail_sinks:
        lines.append("No power rail information available.\n")
        return "\n".join(lines)

    # Build tree
    all_rails = sorted(set(rail_sources.keys()) | set(rail_sinks.keys()))
    lines.append("```")
    for rail in all_rails:
        sources = rail_sources.get(rail, ["external"])
        sinks = rail_sinks.get(rail, [])
        src_str = ", ".join(sources[:3])
        if len(sources) > 3:
            src_str += f" +{len(sources) - 3}"
        ordered_sinks = sorted(sinks, key=lambda item: (":" in item, item))
        sink_str = ", ".join(ordered_sinks[:5])
        if len(sinks) > 5:
            sink_str += f" +{len(sinks) - 5}"
        lines.append(f"  {src_str} -> [{rail}] -> {sink_str}")
    lines.append("```\n")
    return "\n".join(lines)


def _bom_summary_section(components: list[ComponentDef]) -> str:
    """Generate BOM summary table."""
    lines = ["## BOM Summary\n"]

    # Count by category
    categories: dict[str, int] = {}
    total_pins = 0
    for comp in components:
        cat = comp.category or "other"
        categories[cat] = categories.get(cat, 0) + 1
        total_pins += len(comp.pins)

    passive_count = sum(len(comp.bypass_caps) + len(comp.straps) for comp in components)

    lines.append(f"- **Total ICs:** {len(components)}")
    lines.append(f"- **Total passive instances:** {passive_count}")
    lines.append(f"- **Total pins:** {total_pins}")
    lines.append("")

    lines.append("| Category | Count |")
    lines.append("|-|-|")
    for cat in sorted(categories.keys()):
        lines.append(f"| {cat} | {categories[cat]} |")
    lines.append("")

    # Component list
    lines.append("### Component List\n")
    lines.append("| Ref | MPN | Value | Category | Pins | Bypass | Straps |")
    lines.append("|-|-|-|-|-|-|-|")
    for comp in components:
        ref = comp.source_ref or "-"
        mpn = comp.source_mpn or comp.mpn
        val = comp.value
        lines.append(
            f"| {ref} | {mpn} | {val} | {comp.category} "
            f"| {len(comp.pins)} | {len(comp.bypass_caps)} | {len(comp.straps)} |"
        )
    lines.append("")
    return "\n".join(lines)


def _design_rationale_section(components: list[ComponentDef]) -> str:
    """Collect per-component annotations into a design rationale section."""
    lines = ["## Design Rationale\n"]
    has_content = False

    for comp in components:
        if not comp.annotations:
            continue
        has_content = True
        ref = comp.source_ref or comp.mpn
        lines.append(f"### {ref} — {comp.mpn}\n")
        for ann in comp.annotations:
            lines.append(f"- {ann}")
        lines.append("")

    if not has_content:
        lines.append("No component annotations available.\n")
    return "\n".join(lines)


def _validation_section(validation_results) -> str:
    """Format validation results into report section."""
    lines = ["## Circuit Validation\n"]

    if not validation_results:
        lines.append("No validation results available.\n")
        return "\n".join(lines)

    total_issues = sum(len(r.issues) for r in validation_results)
    if total_issues == 0:
        lines.append("All checks passed — no algebraic circuit issues detected.\n")

    for result in validation_results:
        status_icon = "PASS" if result.status == "PASS" else "**" + result.status + "**"
        lines.append(f"- {status_icon}: {result.label}")
        for issue in result.issues:
            lines.append(f"  - [{issue.level.upper()}] {issue.ref} {issue.mpn}: {issue.message}")
    lines.append("")
    return "\n".join(lines)


def generate_report(
    components: list[ComponentDef],
    validation_results=None,
    output_path: str | Path = "design_report.md",
    metadata: dict | None = None,
) -> Path:
    """Generate a markdown design report.

    Args:
        components: list of ComponentDefs (after overlay/template resolution)
        validation_results: list of ValidationCheckResult from validator.py (optional)
        output_path: where to write the report
        metadata: dict with project/company/spec_path keys

    Returns: Path to the generated report file.
    """
    metadata = metadata or {}
    project = metadata.get("project", "Project")
    company = metadata.get("company", "")
    date = datetime.date.today().isoformat()

    sections = []
    sections.append(f"# {project} — Design Report\n")
    if company:
        sections.append(f"**Company:** {company}  ")
    sections.append(f"**Date:** {date}  ")
    sections.append(f"**Components:** {len(components)}  ")
    if metadata.get("spec_path"):
        sections.append(f"**Source:** `{metadata['spec_path']}`  ")
    sections.append("")

    sections.append(_power_tree_section(components))
    sections.append(_bom_summary_section(components))
    sections.append(_design_rationale_section(components))
    if validation_results is not None:
        sections.append(_validation_section(validation_results))

    content = "\n".join(sections)
    output_path = Path(output_path)
    output_path.write_text(content, encoding="utf-8", newline="")
    return output_path
