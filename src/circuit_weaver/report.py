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
from typing import Iterable

from .component_db import ComponentDef


def _evidence_traceability_section(evidence_manifest: str | Path | None, evidence_ids: Iterable[str] | None) -> str:
    """Render portable evidence references without claiming missing provenance."""

    manifest_reference = ""
    if evidence_manifest is not None:
        manifest_path = Path(evidence_manifest)
        if manifest_path.is_absolute() or ".." in manifest_path.parts:
            raise ValueError("evidence_manifest must be an output-relative path")
        manifest_reference = manifest_path.as_posix()
    ids = sorted({evidence_id for evidence_id in (evidence_ids or []) if isinstance(evidence_id, str)})
    if not manifest_reference and not ids:
        return ""
    lines = ["## Evidence Traceability", ""]
    if manifest_reference:
        lines.append(f"- Evidence manifest: [`{manifest_reference}`]({manifest_reference})")
    if ids:
        lines.append("- Referenced evidence IDs: " + ", ".join(f"`{evidence_id}`" for evidence_id in ids))
    lines.append("")
    return "\n".join(lines)


def _power_tree_section(components: list[ComponentDef]) -> str:
    """Generate a text-based power tree from component power pin assignments.

    Only real power rails appear: nets attached to component power pins or
    produced as a regulator output. Per-instance internal nodes (switch
    nodes, bootstrap nets) and support-passive plumbing stay out of the tree.
    """
    lines = ["## Power Tree\n"]
    ground_nets = {"GND", "AGND", "DGND", "PGND", "GNDA"}

    rail_sources: dict[str, list[str]] = {}  # rail -> source refs
    rail_sinks: dict[str, list[str]] = {}  # rail -> consumer refs
    power_rail_nets: set[str] = set()  # nets that qualify as rails
    envelopes: dict[str, list[tuple[str, object]]] = {}

    def _add(bucket: dict[str, list[str]], net: str, ref: str) -> None:
        refs = bucket.setdefault(net, [])
        if ref not in refs:
            refs.append(ref)

    def _field(item: object, *names: str) -> object | None:
        for name in names:
            value = getattr(item, name, None)
            if value is not None:
                return value
        return None

    def _text(value: object | None) -> str:
        if value is None or value == "":
            return "—"
        if isinstance(value, float):
            return f"{value:g}"
        if isinstance(value, (tuple, list)):
            return ", ".join(str(part) for part in value) or "—"
        if isinstance(value, dict):
            return ", ".join(f"{key}={value[key]}" for key in sorted(value)) or "—"
        return str(value)

    for comp in components:
        ref = comp.source_ref or comp.mpn
        pin_types = {pin.number: pin.electrical_type for pin in comp.pins}

        # Rails this component produces (regulator outputs). Detected from
        # power_out pins plus the output-cap / feedback-divider metadata,
        # which covers regulators whose rail is reached through an external
        # inductor rather than a direct output pin.
        output_nets: set[str] = set()
        if comp.category == "power":
            for bc in comp.bypass_caps:
                if bc.role == "output_cap" or bc.pin.upper() in ("COUT", "OUT"):
                    output_nets.add(bc.net)
            for strap in comp.straps:
                if "FB" in strap.pin.upper():
                    output_nets.add(strap.rail)
        output_nets -= ground_nets

        for pin_num, net in comp.power_pins.items():
            if net in ground_nets:
                continue
            power_rail_nets.add(net)
            if pin_types.get(pin_num) == "power_out" or net in output_nets:
                _add(rail_sources, net, ref)
            else:
                _add(rail_sinks, net, ref)

        for net in output_nets:
            power_rail_nets.add(net)
            _add(rail_sources, net, ref)

        # Typed requirements are additive to pin metadata. Missing envelope
        # values remain unknown instead of being converted to nominal guesses.
        for requirement in getattr(comp, "power_reqs", []) or []:
            net = _field(requirement, "net", "rail", "name")
            if not isinstance(net, str) or not net or net in ground_nets:
                continue
            power_rail_nets.add(net)
            direction = str(_field(requirement, "direction") or "").lower()
            if direction in {"source", "bidirectional"}:
                _add(rail_sources, net, ref)
            if direction in {"load", "bidirectional"}:
                _add(rail_sinks, net, ref)
            envelopes.setdefault(net, []).append((ref, requirement))

        # Decoupling on a rail marks the component as one of its consumers.
        for bc in comp.bypass_caps:
            if bc.net not in ground_nets and bc.net not in output_nets:
                _add(rail_sinks, bc.net, ref)

    rails = sorted(net for net in (set(rail_sources) | set(rail_sinks)) if net in power_rail_nets)
    if not rails:
        lines.append("No power rail information available.\n")
        return "\n".join(lines)

    lines.append("```")
    for rail in rails:
        sources = rail_sources.get(rail) or ["external"]
        src_str = ", ".join(sources[:3])
        if len(sources) > 3:
            src_str += f" +{len(sources) - 3}"
        # A rail's source is not also listed among its consumers.
        sinks = [r for r in rail_sinks.get(rail, []) if r not in sources]
        sink_str = ", ".join(sinks[:6])
        if len(sinks) > 6:
            sink_str += f" +{len(sinks) - 6}"
        if not sink_str:
            sink_str = "(no consumers)"
        lines.append(f"  {src_str} -> [{rail}] -> {sink_str}")
    lines.append("```\n")
    if envelopes:
        lines.extend(
            [
                "### Operating Envelopes\n",
                (
                    "| Rail | Ref | Direction | Vmin (V) | Vnom (V) | Vmax (V) | Steady (mA) | "
                    "Peak (mA) | Sequencing | Tolerance | Provenance |"
                ),
                "|-|-|-|-|-|-|-|-|-|-|-|",
            ]
        )
        for rail in sorted(envelopes):
            for ref, requirement in sorted(envelopes[rail], key=lambda item: item[0]):
                lines.append(
                    "| "
                    + " | ".join(
                        [
                            rail,
                            ref,
                            _text(_field(requirement, "direction")),
                            _text(_field(requirement, "v_min", "voltage_min_v")),
                            _text(_field(requirement, "v_nominal", "voltage", "voltage_nominal_v")),
                            _text(_field(requirement, "v_max", "voltage_max_v")),
                            _text(_field(requirement, "i_steady_ma", "steady_current_ma")),
                            _text(_field(requirement, "i_peak_ma", "peak_current_ma", "max_current_ma")),
                            _text(
                                _field(
                                    requirement,
                                    "sequencing",
                                    "sequence",
                                    "sequence_order",
                                    "sequence_dependency",
                                )
                            ),
                            _text(_field(requirement, "tolerance")),
                            _text(_field(requirement, "provenance", "evidence_id")),
                        ]
                    )
                    + " |"
                )
        lines.append("")
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

    lines.append(f"- **Placed components:** {len(components)}")
    lines.append(f"- **Support passives (bypass caps, straps):** {passive_count}")
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
    evidence_manifest: str | Path | None = None,
    evidence_ids: Iterable[str] | None = None,
) -> Path:
    """Generate a markdown design report.

    Args:
        components: list of ComponentDefs (after overlay/template resolution)
        validation_results: list of ValidationCheckResult from validator.py (optional)
        output_path: where to write the report
        metadata: dict with project/company/spec_path keys
        evidence_manifest: output-relative path to the evidence ledger, if available
        evidence_ids: evidence IDs referenced by the report, if available

    Returns: Path to the generated report file.
    """
    metadata = metadata or {}
    project = metadata.get("project", "Project")
    company = metadata.get("company", "")
    description = metadata.get("description", "")
    date = datetime.date.today().isoformat()

    sections = []
    sections.append(f"# {project} — Design Report\n")
    if description:
        sections.append(f"{description}\n")
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
    sections.append(_evidence_traceability_section(evidence_manifest, evidence_ids))

    try:
        from . import __version__ as _cw_version
    except ImportError:  # pragma: no cover
        _cw_version = "unknown"
    sections.append(
        f"---\n\n*Generated by [Circuit Weaver](https://pypi.org/project/circuit-weaver/) v{_cw_version}.*\n"
    )

    content = "\n".join(sections)
    output_path = Path(output_path)
    output_path.write_text(content, encoding="utf-8", newline="")
    return output_path
