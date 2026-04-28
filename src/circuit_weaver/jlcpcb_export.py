"""JLCPCB BOM and CPL export for assembly ordering.

Generates:
- BOM CSV (Comment, Designator, Footprint, LCSC Part#)
- CPL CSV (Designator, Mid X, Mid Y, Rotation, Layer)
- README.txt with upload instructions

Usage:
    from circuit_weaver.jlcpcb_export import export_jlcpcb
    result = export_jlcpcb(spec, output_dir="/tmp/jlcpcb_export")
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .component_db import ComponentDef
from .pcb_export import generate_pcb_placement


def group_bom_rows(components: list[ComponentDef]) -> list[dict[str, Any]]:
    """Group components into BOM rows by (value, footprint, lcsc_pn).

    Returns list of dicts:
        {
            "comment": str,          # value or MPN
            "designators": str,      # comma-separated sorted refs
            "footprint": str,        # last segment after ':'
            "lcsc_pn": str,          # LCSC part number or empty
            "has_lcsc": bool,        # whether LCSC number is present
        }
    """
    # Group by (value, footprint, lcsc_pn)
    groups: dict[tuple, list[str]] = {}

    for comp in components:
        # Skip passives/straps without source_ref (no designators to group)
        if not comp.source_ref:
            continue

        # Extract footprint last segment (e.g., "SOT-23-6" from "Package_TO_SOT_SMD:SOT-23-6")
        footprint = comp.footprint
        if ":" in footprint:
            footprint = footprint.split(":")[-1]

        # Group key
        comment = comp.value or comp.source_mpn or comp.mpn
        key = (comment, footprint, comp.lcsc_pn or "")

        if key not in groups:
            groups[key] = []
        groups[key].append(comp.source_ref)

    # Build rows
    rows = []
    for (comment, footprint, lcsc_pn), refs in sorted(groups.items()):
        rows.append(
            {
                "comment": comment,
                "designators": ",".join(sorted(refs)),
                "footprint": footprint,
                "lcsc_pn": lcsc_pn,
                "has_lcsc": bool(lcsc_pn),
            }
        )

    return rows


def write_jlcpcb_bom(bom_rows: list[dict], output_path: Path) -> None:
    """Write JLCPCB BOM CSV.

    Columns: Comment, Designator, Footprint, LCSC Part#
    """
    lines = []
    lines.append("Comment,Designator,Footprint,LCSC Part#")

    for row in bom_rows:
        # CSV escape: wrap in quotes if contains comma
        comment = row["comment"]
        if "," in comment:
            comment = f'"{comment}"'

        lcsc = row["lcsc_pn"] if row["has_lcsc"] else ""

        lines.append(f"{comment},{row['designators']},{row['footprint']},{lcsc}")

    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_jlcpcb_cpl(
    components: list[ComponentDef],
    placements: dict[str, tuple[float, float, float, str]],
    output_path: Path,
) -> None:
    """Write JLCPCB CPL (centroid/placement) CSV.

    Columns: Designator, Mid X, Mid Y, Rotation, Layer
    """
    lines = []
    lines.append("Designator,Mid X,Mid Y,Rotation,Layer")

    # Collect only components with source_ref that have placement data
    for comp in components:
        if not comp.source_ref or comp.source_ref not in placements:
            continue

        x, y, rotation, layer = placements[comp.source_ref]

        # JLCPCB layer convention: "top" for F.Cu, "bottom" for B.Cu
        jlcpcb_layer = "top" if layer == "top" else "bottom"

        lines.append(f"{comp.source_ref},{x:.2f},{y:.2f},{rotation:.1f},{jlcpcb_layer}")

    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_dual_sided_cpl(
    components: list[ComponentDef],
    placements: dict[str, tuple[float, float, float, str]],
    output_dir: Path,
    *,
    assembly_mode: str = "dual-sided-sequential",
) -> dict:
    """Write separate top/bottom CPL files for dual-sided assembly."""
    top_lines = ["Designator,Mid X,Mid Y,Rotation,Layer"]
    bottom_lines = ["Designator,Mid X,Mid Y,Rotation,Layer"]
    warnings: list[str] = []
    bottom_refs: list[str] = []

    for comp in components:
        ref = comp.source_ref or ""
        if not ref or ref not in placements:
            continue
        x, y, rotation, layer = placements[ref]
        jlcpcb_layer = "top" if layer in ("top", "front", "F.Cu") else "bottom"
        line = f"{ref},{x:.2f},{y:.2f},{rotation:.1f},{jlcpcb_layer}"
        if jlcpcb_layer == "top":
            top_lines.append(line)
        else:
            bottom_lines.append(line)
            bottom_refs.append(ref)

    for comp in components:
        ref = comp.source_ref or ""
        if ref not in bottom_refs:
            continue
        fp = (comp.footprint or "").upper()
        if any(kw in fp for kw in ("THT", "CONN", "USB", "BARREL", "HEADER")):
            warnings.append(f"{ref}: tall/THT component on bottom side — may interfere with stacking")
        if any(kw in fp for kw in ("QFN", "BGA", "DFN")):
            warnings.append(f"{ref}: {fp} on bottom side — ensure thermal pad vias exist (solder wicking risk)")

    if assembly_mode == "single-sided" and len(bottom_lines) > 1:
        warnings.append(f"{len(bottom_lines) - 1} components assigned to bottom but assembly mode is single-sided")
    if assembly_mode == "dual-sided-simultaneous":
        warnings.append(
            "Simultaneous reflow: verify thermal profile handles both sides. Heavy bottom components may fall."
        )

    output_dir.mkdir(parents=True, exist_ok=True)
    top_path = output_dir / "cpl_top.csv"
    bottom_path = output_dir / "cpl_bottom.csv"
    top_path.write_text("\n".join(top_lines) + "\n", encoding="utf-8")
    bottom_path.write_text("\n".join(bottom_lines) + "\n", encoding="utf-8")

    return {
        "top_file": str(top_path),
        "bottom_file": str(bottom_path),
        "top_count": len(top_lines) - 1,
        "bottom_count": len(bottom_lines) - 1,
        "assembly_mode": assembly_mode,
        "warnings": warnings,
    }


def _variant_file_token(name: str) -> str:
    """Return a filesystem-safe token for an assembly variant name."""
    token = "".join(ch.lower() if ch.isalnum() else "_" for ch in (name or "default"))
    token = "_".join(part for part in token.split("_") if part)
    return token or "default"


def generate_assembly_variants(
    components: list[ComponentDef],
    variants: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Generate component subsets for JLCPCB assembly variants.

    Variant specs are deliberately simple and data-oriented so they can be
    emitted by design YAML, a future CLI flag, or downstream ordering tools:

    ``{"name": "sensorless", "exclude_refs": ["U2"], "dnp_refs": ["R5"]}``

    ``include_refs`` is optional. If present, only those designators are
    considered. ``exclude_refs`` and ``dnp_refs`` then remove components from
    the assembly set. Returned entries contain the filtered ComponentDef list,
    generated BOM rows, and reference bookkeeping for reporting/tests.
    """
    specs = variants or [{"name": "default"}]
    by_ref = {comp.source_ref: comp for comp in components if comp.source_ref}
    all_refs = set(by_ref)
    out: list[dict[str, Any]] = []
    used_tokens: dict[str, int] = {}

    for idx, spec in enumerate(specs):
        name = str(spec.get("name") or f"variant_{idx + 1}")
        base_token = _variant_file_token(name)
        token_count = used_tokens.get(base_token, 0) + 1
        used_tokens[base_token] = token_count
        token = base_token if token_count == 1 else f"{base_token}_{token_count}"
        include_refs = {str(ref) for ref in spec.get("include_refs", []) if str(ref)}
        exclude_refs = {str(ref) for ref in spec.get("exclude_refs", []) if str(ref)}
        dnp_refs = {str(ref) for ref in spec.get("dnp_refs", []) if str(ref)}

        candidate_refs = include_refs if include_refs else all_refs
        assembled_refs = sorted((candidate_refs & all_refs) - exclude_refs - dnp_refs)
        assembled_components = [by_ref[ref] for ref in assembled_refs]
        omitted_refs = sorted((all_refs - set(assembled_refs)) | exclude_refs | dnp_refs)

        out.append(
            {
                "name": name,
                "token": token,
                "components": assembled_components,
                "bom_rows": group_bom_rows(assembled_components),
                "included_refs": assembled_refs,
                "omitted_refs": omitted_refs,
                "dnp_refs": sorted(dnp_refs),
            }
        )

    return out


def write_jlcpcb_readme(project_name: str, output_path: Path) -> None:
    """Write JLCPCB upload instructions and notes."""
    lines = []
    lines.append("JLCPCB PCB Assembly Upload Instructions")
    lines.append("=" * 50)
    lines.append("")
    lines.append(f"Project: {project_name}")
    lines.append("")
    lines.append("Files Included:")
    lines.append("  - bom_jlcpcb.csv        BOM for parts matching")
    lines.append("  - cpl_jlcpcb.csv        Centroid/placement file")
    lines.append("  - (gerbers/)            Gerber files (export separately from KiCad)")
    lines.append("")
    lines.append("Upload Steps:")
    lines.append("  1. Go to https://jlcpcb.com/quote")
    lines.append("  2. Upload Gerber ZIP file")
    lines.append("  3. Configure PCB: 2-layer, 1.6mm thickness, color, quantity")
    lines.append("  4. Proceed to quote")
    lines.append("  5. Enable 'PCB Assembly'")
    lines.append("  6. Upload BOM file (bom_jlcpcb.csv)")
    lines.append("  7. Upload CPL file (cpl_jlcpcb.csv)")
    lines.append("  8. Review part matching and confirm")
    lines.append("")
    lines.append("Notes:")
    lines.append("  - Parts with empty LCSC Part# must be sourced separately")
    lines.append("  - JLCPCB basic parts (no setup fee): ~700 common components")
    lines.append("  - Extended parts (setup fee $3 each): remaining components")
    lines.append("  - Verify all part matches before confirming order")
    lines.append("")

    output_path.write_text("\n".join(lines), encoding="utf-8")


def _detect_price_breaks(bom_rows: list[dict]) -> list[dict]:
    """Query LCSC pricing for each BOM row and detect price breaks.

    For each row with an LCSC part number, attempts to fetch pricing at
    standard quantity tiers (1, 10, 100). Returns price-break alerts
    where ordering higher quantity reduces per-unit cost by > 20%.

    Returns list of alert dicts:
        {
            "designators": str,
            "lcsc_pn": str,
            "price_1": float,    # price at qty 1
            "price_10": float,   # price at qty 10 (or same as qty 1)
            "price_100": float,  # price at qty 100 (or same as qty 1)
            "savings_pct_100": float,  # savings % at qty 100 vs qty 1
        }
    """
    alerts: list[dict] = []

    for row in bom_rows:
        lcsc_pn = row.get("lcsc_pn", "")
        if not lcsc_pn:
            continue

        try:
            from .parts_lookup import PartsLookup

            lookup = PartsLookup()
            result = lookup.lookup_by_lcsc(lcsc_pn)
            if not result:
                continue

            # Extract pricing from LCSC result
            prices = result.get("prices", {}) or {}
            price_1 = _parse_price(prices.get("1", prices.get("qty_1", "")))
            price_10 = _parse_price(prices.get("10", prices.get("qty_10", "")))
            price_100 = _parse_price(prices.get("100", prices.get("qty_100", "")))

            # Fall back to price field if-tiered data unavailable
            single_price = result.get("price", 0)
            if not price_1 and single_price:
                price_1 = float(single_price)

            if price_1:
                price_10 = price_10 or price_1
                price_100 = price_100 or price_1

                savings_100 = 0.0
                if price_1 > 0 and price_100 < price_1:
                    savings_100 = round((1 - price_100 / price_1) * 100, 1)

                if savings_100 >= 20:
                    alerts.append({
                        "designators": row.get("designators", ""),
                        "lcsc_pn": lcsc_pn,
                        "price_1": price_1,
                        "price_10": price_10,
                        "price_100": price_100,
                        "savings_pct_100": savings_100,
                    })
        except Exception:
            continue

    return alerts


def _parse_price(raw: str | float | int | None) -> float:
    """Parse a price string to float, returning 0.0 on failure."""
    if raw is None:
        return 0.0
    if isinstance(raw, (int, float)):
        return float(raw)
    try:
        return float(str(raw).strip().replace("$", "").replace(",", ""))
    except (ValueError, AttributeError):
        return 0.0


def _append_price_breaks(readme_path: Path, alerts: list[dict]) -> None:
    """Append price-break cost-saving tips to the assembly README."""
    lines = [
        "",
        "=" * 60,
        "PRICE-BREAK ALERTS — Cost-saving opportunities",
        "=" * 60,
        "",
        "The following components have significant price breaks at higher quantity:",
        "",
    ]
    for alert in sorted(alerts, key=lambda a: -a["savings_pct_100"]):
        refs = alert["designators"]
        pn = alert["lcsc_pn"]
        p1 = alert["price_1"]
        p100 = alert["price_100"]
        savings = alert["savings_pct_100"]
        lines.append(f"  {refs} ({pn}):")
        lines.append(f"    \u2022 ${p1:.4f} @ qty 1")
        lines.append(f"    \u2022 ${p100:.4f} @ qty 100 (save {savings:.0f}%)")
        lines.append("")

    try:
        with open(readme_path, "a", encoding="utf-8") as f:
            f.write("\n".join(lines))
    except OSError:
        pass


def export_jlcpcb(
    spec: dict[str, Any],
    output_dir: str | Path,
    enrich_parts: bool = False,
    assembly_variants: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Export JLCPCB BOM and CPL files.

    Args:
        spec: Design spec dict (same format as passed to validate_design)
        output_dir: Directory to write BOM/CPL/README files
        enrich_parts: (reserved for future use) Whether to enrich part info via APIs
        assembly_variants: Optional assembly variants. Each item may contain
            name, include_refs, exclude_refs, and dnp_refs.

    Returns:
        Summary dict: {
            "status": "ok" | "error",
            "message": str,
            "files": [...],
            "component_count": int,
            "bom_rows": int,
            "missing_lcsc": int,
        }
    """
    try:
        from .dispatcher import compile_design_ir

        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        # Step 1: Compile the design
        compiled = compile_design_ir(spec)
        components = compiled.components
        project_name = spec.get("project", "Design")

        # Step 2: Generate PCB placement (includes placements dict)
        _pcb_file, placements = generate_pcb_placement(components, output_dir, project_name)

        # Step 3: Group BOM by (value, footprint, lcsc_pn)
        bom_rows = group_bom_rows(components)

        # Step 4: Detect price breaks
        price_breaks = _detect_price_breaks(bom_rows)

        # Step 5: Write files
        bom_path = output_dir / "bom_jlcpcb.csv"
        cpl_path = output_dir / "cpl_jlcpcb.csv"
        readme_path = output_dir / "README.txt"

        write_jlcpcb_bom(bom_rows, bom_path)
        write_jlcpcb_cpl(components, placements, cpl_path)
        write_jlcpcb_readme(project_name, readme_path)

        variant_outputs: list[dict[str, Any]] = []
        if assembly_variants:
            for variant in generate_assembly_variants(components, assembly_variants):
                token = variant["token"]
                variant_bom = output_dir / f"bom_jlcpcb_{token}.csv"
                variant_cpl = output_dir / f"cpl_jlcpcb_{token}.csv"
                write_jlcpcb_bom(variant["bom_rows"], variant_bom)
                write_jlcpcb_cpl(variant["components"], placements, variant_cpl)
                variant_outputs.append(
                    {
                        "name": variant["name"],
                        "bom": str(variant_bom),
                        "cpl": str(variant_cpl),
                        "component_count": len(variant["components"]),
                        "bom_rows": len(variant["bom_rows"]),
                        "dnp_refs": variant["dnp_refs"],
                    }
                )

        # Append price-break tips to README
        if price_breaks:
            _append_price_breaks(readme_path, price_breaks)

        # Count missing LCSC numbers
        missing_lcsc = sum(1 for row in bom_rows if not row["has_lcsc"])

        return {
            "status": "ok",
            "message": f"Exported JLCPCB BOM and CPL for {project_name}",
            "files": [
                str(bom_path),
                str(cpl_path),
                str(readme_path),
                *[item["bom"] for item in variant_outputs],
                *[item["cpl"] for item in variant_outputs],
            ],
            "component_count": len(components),
            "bom_rows": len(bom_rows),
            "missing_lcsc": missing_lcsc,
            "price_breaks": len(price_breaks),
            "assembly_variants": variant_outputs,
        }

    except Exception as e:
        return {
            "status": "error",
            "message": str(e),
            "files": [],
            "component_count": 0,
            "bom_rows": 0,
            "missing_lcsc": 0,
        }
