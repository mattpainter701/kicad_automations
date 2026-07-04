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


def _fab_notes_section(components: list[ComponentDef]) -> str:
    """Generate fabrication recommendations based on component packages."""
    lines = ["## Fabrication Notes\n"]

    if not components:
        lines.append("No components — no fabrication recommendations.\n")
        return "\n".join(lines)

    # Analyze footprints
    footprints = [c.footprint.upper() if c.footprint else "" for c in components]
    has_bga = any("BGA" in fp for fp in footprints)
    has_qfn = any("QFN" in fp or "LGA" in fp for fp in footprints)
    has_qfp = any("QFP" in fp or "TQFP" in fp for fp in footprints)

    # Layer recommendations
    layer_rec = "4-layer minimum (recommended 6-layer for thermal)" if has_bga else "2-layer sufficient"

    # Surface finish recommendations
    finish_rec = "ENIG or HASL lead-free (ENIG preferred for reliability)"
    if has_bga:
        finish_rec = "ENIG (mandatory for BGA)"

    lines.append("**PCB Specification:**")
    lines.append(f"- Layer count: {layer_rec}")
    lines.append(f"- Surface finish: {finish_rec}")
    lines.append("- Solder type: Lead-free (RoHS)")
    lines.append("")

    # Assembly recommendations
    asm_notes = []
    if has_bga:
        asm_notes.append("**BGA Assembly** — Requires X-ray inspection and controlled reflow profile")
    if has_qfn or has_qfp:
        asm_notes.append("**Fine-Pitch Components** — Paste stencil required; thermal pad via array recommended")
    asm_notes.append("**SMT Assembly** — Stencil, pick-and-place, and reflow furnace required")

    if asm_notes:
        lines.append("**Assembly Notes:**")
        for note in asm_notes:
            lines.append(f"- {note}")
        lines.append("")

    lines.append("**Design Checklist:**")
    lines.append("- [ ] Gerbers exported and verified with Gerber viewer")
    lines.append("- [ ] Component footprints match datasheets (especially fine-pitch packages)")
    lines.append("- [ ] Thermal vias present under power dissipation components")
    lines.append("- [ ] Solder mask clearance verified (0.1mm min from pad)")
    lines.append("- [ ] Silkscreen text readable (>0.8mm height, >0.15mm width)")
    lines.append("")

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


def verify_report_fidelity(report_text: str, components: list[ComponentDef]) -> dict:
    """Sprint 40 Task 172 — audit a report for references to components or
    nets that don't exist in the emitted design.

    Returns a dict with three lists:
    * ``ghost_refs``  — reference designators named in the report that are
      not attached to any component in ``components``.
    * ``ghost_nets``  — net names named in the report that no component
      connects to.
    * ``stub_annotations`` — component annotations that mention pin assignments
      or supporting passives the component doesn't actually carry.

    This is a regression check. The report is allowed to describe design
    intent, but every reference / net it calls out by name must be present
    in the emitted schematic. Ghost features are how the IoT AQ audit ended
    up with a report claiming "BME688 I2C + pull-ups" when the schematic had
    zero wires for the sensor.

    Not a hard validator today — this is a diagnostic callers can run. The
    test suite uses it to catch generator regressions; adopting as a
    generate-time gate is a follow-up once ghost-free templates are
    confirmed across the Sprint 40 corpus.
    """
    import re

    known_refs = {c.source_ref for c in components if c.source_ref}
    known_nets: set[str] = set()
    for c in components:
        known_nets.update(c.all_signal_nets())
        known_nets.update(c.all_power_nets())
        for bc in c.bypass_caps:
            if bc.net:
                known_nets.add(bc.net)
            if bc.gnd_net:
                known_nets.add(bc.gnd_net)
        for strap in c.straps:
            if strap.net:
                known_nets.add(strap.net)
            if strap.rail:
                known_nets.add(strap.rail)

    ref_pattern = re.compile(r"(?<![A-Za-z0-9_])([A-Z]{1,3}\d{1,4})(?![A-Za-z0-9_])")
    net_pattern = re.compile(
        r"(?<![A-Za-z0-9_])"
        r"(VBAT|GND|AGND|DGND|PGND|VCC(?:[A-Z0-9_]+)?|VDD(?:[A-Z0-9_]+)?|"
        r"SDA|SCL|SWDIO|SWO|SWCLK|NRESET|MOSI|MISO|SCK|TX(?:D\d?)?|RX(?:D\d?)?)"
        r"(?![A-Za-z0-9_])"
    )

    mentioned_refs = set(ref_pattern.findall(report_text))
    mentioned_nets = set(net_pattern.findall(report_text))

    ghost_refs = sorted(mentioned_refs - known_refs)
    ghost_nets = sorted(mentioned_nets - known_nets)

    stub_annotations = []
    for c in components:
        for ann in c.annotations:
            # If the annotation names a ref that isn't this component and
            # isn't in the known set, it's a ghost claim.
            for ann_ref in ref_pattern.findall(ann):
                if ann_ref != c.source_ref and ann_ref not in known_refs:
                    stub_annotations.append(
                        {
                            "owner": c.source_ref,
                            "annotation": ann,
                            "ghost_ref": ann_ref,
                        }
                    )

    return {
        "ghost_refs": ghost_refs,
        "ghost_nets": ghost_nets,
        "stub_annotations": stub_annotations,
    }


def _layout_quality_section(reports: dict) -> str:
    """Render per-sheet geometric layout-quality results (T239).

    ``reports`` maps sheet filename -> LayoutQualityReport from
    ``layout_quality.analyze_schematic_file``.
    """
    lines = ["## Layout Quality\n"]
    lines.append("| Sheet | Symbols | Body overlaps | Wire-body crossings |")
    lines.append("|-------|---------|---------------|---------------------|")
    any_dirty = False
    for filename, report in sorted(reports.items()):
        overlaps = len(getattr(report, "overlaps", []) or [])
        crossings = getattr(report, "wire_body_crossings", 0)
        symbols = getattr(report, "symbols", 0)
        if overlaps or crossings:
            any_dirty = True
        lines.append(f"| `{filename}` | {symbols} | {overlaps} | {crossings} |")
    if any_dirty:
        lines.append("")
        lines.append(
            "⚠️ Sheets with overlaps or crossings will read as cluttered in KiCad — "
            "review placement before fabrication sign-off."
        )
    else:
        lines.append("")
        lines.append("All sheets are geometrically clean (no overlaps, no wire-body crossings).")
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
    sections.append(_fab_notes_section(components))
    if validation_results is not None:
        sections.append(_validation_section(validation_results))
    if metadata.get("layout_quality"):
        sections.append(_layout_quality_section(metadata["layout_quality"]))

    content = "\n".join(sections)
    output_path = Path(output_path)
    output_path.write_text(content, encoding="utf-8", newline="")
    return output_path
