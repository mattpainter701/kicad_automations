"""SVG placement editor — bidirectional conversion for PCB placement data.

Exports PCB component placements as an SVG diagram that users can edit in
Inkscape/CorelDRAW, then imports the edited SVG back to update KiCad .kicad_pcb
and CPL files.

Usage:
    from circuit_weaver.svg_placement import export_placement_svg, import_placement_from_svg

    # Export placement to SVG
    svg_path = export_placement_svg(components, placements, 100, 80, output_path="placement.svg")

    # User edits SVG in Inkscape...

    # Import edited SVG back
    updated_placements = import_placement_from_svg("placement.svg")
    update_kicad_pcb_placements("design.kicad_pcb", updated_placements, output_path="design.kicad_pcb")
"""

from __future__ import annotations

import csv
import math
import re
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

_SCALE = 10.0  # px per mm
_SVG_NS = "http://www.w3.org/2000/svg"
_CATEGORY_COLORS = {
    "power": "#FF6B6B",
    "regulator": "#FF6B6B",
    "digital": "#4ECDC4",
    "mcu": "#4ECDC4",
    "fpga": "#4ECDC4",
    "connector": "#95E1D3",
    "usb": "#95E1D3",
    "passive": "#FEC89A",
    "sensor": "#A8E6CF",
    "rf": "#C3A6FF",
    "misc": "#CCCCCC",
}

# Component size heuristics (width x height in mm)
_COMPONENT_SIZES = {
    "0402": (1.0, 0.5),
    "0603": (1.6, 0.8),
    "0805": (2.0, 1.25),
    "1206": (3.2, 1.6),
    "1210": (3.2, 2.5),
    "SOT-23": (4.0, 3.0),
    "SOT-23-5": (4.0, 3.0),
    "SOT-23-6": (4.0, 3.0),
    "SOT-89": (4.5, 3.5),
    "SOT-223": (6.5, 3.4),
    "SOIC-8": (6.0, 5.0),
    "SOIC-16": (10.0, 6.0),
    "TSSOP-8": (4.4, 3.0),
    "TSSOP-16": (4.4, 5.0),
    "QFN-16": (3.0, 3.0),
    "QFN-20": (4.0, 4.0),
    "QFN-32": (6.0, 6.0),
    "BGA-256": (23.0, 23.0),
}

ET.register_namespace("", _SVG_NS)


def _get_component_size(component: dict[str, Any]) -> tuple[float, float]:
    """Estimate component width and height in mm from footprint.

    Falls back to heuristic sizes for common packages.
    """
    footprint = component.get("footprint", "")
    if not footprint:
        return (4.0, 3.0)  # default

    # Try exact footprint match
    footprint_base = Path(footprint).stem  # e.g., "R_0402_1005Metric" → "R_0402_1005Metric"
    for key, size in _COMPONENT_SIZES.items():
        if key in footprint_base:
            return size

    # Default: assume IC-like component
    return (12.0, 12.0)


def export_placement_svg(
    components: list[dict[str, Any]],
    placements: dict[str, dict[str, Any]],
    board_width_mm: float,
    board_height_mm: float,
    output_path: Path | str | None = None,
    *,
    scale: float = _SCALE,
    title: str = "PCB Placement",
) -> str:
    """Export PCB placements to an editable SVG diagram.

    Args:
        components: List of component dicts with ref, value, footprint, category.
        placements: Dict mapping ref → {x, y, rotation, layer} in mm.
        board_width_mm: Board width in mm.
        board_height_mm: Board height in mm.
        output_path: Write SVG to this file. If None, returns SVG string only.
        scale: Pixels per mm (default 10).
        title: SVG title/heading.

    Returns:
        SVG string (XML).
    """
    width_px = int(board_width_mm * scale)
    height_px = int(board_height_mm * scale)

    # Create root SVG element
    svg = ET.Element(
        "svg",
        {
            "xmlns": _SVG_NS,
            "width": str(width_px),
            "height": str(height_px),
            "viewBox": f"0 0 {width_px} {height_px}",
            "data-scale-px-per-mm": str(scale),
        },
    )

    # Add title
    title_elem = ET.SubElement(svg, "title")
    title_elem.text = title

    # Add board outline
    board_outline = ET.SubElement(
        svg,
        "rect",
        {
            "x": "0",
            "y": "0",
            "width": str(width_px),
            "height": str(height_px),
            "fill": "none",
            "stroke": "#999",
            "stroke-width": "2",
            "data-board-outline": "true",
        },
    )

    # Map components by ref for easy lookup
    comp_by_ref = {c["ref"]: c for c in components if isinstance(c, dict)}

    # Add component groups
    for ref, placement in placements.items():
        comp = comp_by_ref.get(ref)
        if not comp:
            continue

        x_mm = placement.get("x", 0)
        y_mm = placement.get("y", 0)
        rotation = placement.get("rotation", 0)
        layer = placement.get("layer", "front")

        x_px = x_mm * scale
        y_px = y_mm * scale

        # Determine color by category
        category = comp.get("category", "misc")
        color = _CATEGORY_COLORS.get(category, _CATEGORY_COLORS["misc"])

        # Create component group
        g = ET.SubElement(
            svg,
            "g",
            {
                "data-ref": ref,
                "data-value": comp.get("value", ""),
                "data-category": category,
                "data-layer": layer,
                "data-rotation": str(rotation),
                "data-footprint": comp.get("footprint", ""),
                "transform": f"translate({x_px}, {y_px}) rotate({rotation})",
            },
        )

        # Add component rectangle (centered)
        comp_width, comp_height = _get_component_size(comp)
        rect_width = comp_width * scale
        rect_height = comp_height * scale

        opacity = "0.5" if layer == "back" else "1"
        stroke_dasharray = "4 2" if layer == "back" else "none"

        rect = ET.SubElement(
            g,
            "rect",
            {
                "x": str(-rect_width / 2),
                "y": str(-rect_height / 2),
                "width": str(rect_width),
                "height": str(rect_height),
                "fill": color,
                "opacity": opacity,
                "stroke": "#333",
                "stroke-width": "1",
                "stroke-dasharray": stroke_dasharray,
            },
        )

        # Add ref label at origin
        text = ET.SubElement(
            g,
            "text",
            {
                "x": "0",
                "y": "0",
                "text-anchor": "middle",
                "dominant-baseline": "middle",
                "font-size": "10",
                "font-family": "monospace",
                "fill": "#000",
                "pointer-events": "none",
            },
        )
        text.text = ref

    # Convert to string
    tree = ET.ElementTree(svg)
    svg_str = ET.tostring(svg, encoding="unicode", method="xml")

    # Write to file if requested
    if output_path:
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(f'<?xml version="1.0"?>\n{svg_str}', encoding="utf-8")

    return svg_str


def _parse_transform(transform_str: str) -> tuple[float, float, float]:
    """Parse SVG transform string to extract translate(x, y) and rotate(angle).

    Handles multiple SVG transform syntaxes:
    - translate(x, y) or translate(x y) — translation in pixels
    - translate(x) — single argument (y defaults to 0)
    - rotate(angle) or rotate(angle cx cy) — rotation in degrees (ignores center if present)
    - matrix(a b c d e f) — affine matrix (extracts translate + rotation)

    Returns (x_px, y_px, rotation_deg).
    """
    x_px = 0.0
    y_px = 0.0
    rotation = 0.0

    try:
        # Try translate with comma separator first (most common)
        translate_match = re.search(r"translate\(([^,\)]+),\s*([^)]+)\)", transform_str)
        if translate_match:
            x_px = float(translate_match.group(1).strip())
            y_px = float(translate_match.group(2).strip())
        else:
            # Try translate with space separator (GIMP style)
            translate_match = re.search(r"translate\(([^\s)]+)\s+([^)]+)\)", transform_str)
            if translate_match:
                x_px = float(translate_match.group(1).strip())
                y_px = float(translate_match.group(2).strip())
            else:
                # Try single-argument translate (implicit y=0)
                translate_match = re.search(r"translate\(([^)]+)\)", transform_str)
                if translate_match:
                    args = translate_match.group(1).strip()
                    if "," not in args and " " not in args:
                        # Single number — only x is specified
                        x_px = float(args)
                        y_px = 0.0

        # Try rotate(angle [cx cy]) — extract only the angle (first argument)
        rotate_match = re.search(r"rotate\(([^\s)]+)", transform_str)
        if rotate_match:
            rotation = float(rotate_match.group(1).strip())

        # Try matrix(a b c d e f) as fallback (GIMP applies transforms as matrix)
        # For a 2D affine matrix: transform point (0,0) by matrix to get translation
        # Rotation is arctan2(b, a) in degrees
        if not (translate_match or rotate_match):
            matrix_match = re.search(r"matrix\(([^)]+)\)", transform_str)
            if matrix_match:
                parts = [float(x.strip()) for x in matrix_match.group(1).split()]
                if len(parts) >= 6:
                    a, b, c, d, e, f = parts[0], parts[1], parts[2], parts[3], parts[4], parts[5]
                    x_px = e  # translation x
                    y_px = f  # translation y
                    rotation = math.degrees(math.atan2(b, a))  # rotation in degrees
    except (ValueError, AttributeError, IndexError) as exc:
        # Gracefully degrade to defaults on parse error
        logging.debug("Failed to parse SVG transform %r: %s", transform_str, exc)

    return x_px, y_px, rotation


def import_placement_from_svg(svg_path: Path | str, known_refs: set[str] | None = None) -> dict[str, dict[str, Any]]:
    """Import component placements from an edited SVG file.

    Args:
        svg_path: Path to SVG file.
        known_refs: Optional set of valid component refs (for validation).

    Returns:
        Dict mapping ref → {x, y, rotation, layer} in mm.
    """
    svg_path = Path(svg_path)
    tree = ET.parse(svg_path)
    root = tree.getroot()

    # Extract scale from root SVG
    scale_str = root.get("data-scale-px-per-mm", str(_SCALE))
    scale = float(scale_str)

    result = {}

    # Find all component groups
    for g in root.iter(f"{{{_SVG_NS}}}g"):
        ref = g.get("data-ref")
        if not ref:
            continue

        if known_refs and ref not in known_refs:
            continue

        # Parse transform, gracefully handling parse errors
        try:
            transform = g.get("transform", "")
            x_px, y_px, rotation = _parse_transform(transform)
        except Exception as exc:
            logging.warning("Failed to parse transform for component %s: %s, using defaults", ref, exc)
            x_px = y_px = rotation = 0.0

        # Convert pixels to mm
        x_mm = round(x_px / scale, 3)
        y_mm = round(y_px / scale, 3)

        # Get layer
        layer = g.get("data-layer", "front")

        result[ref] = {
            "x": x_mm,
            "y": y_mm,
            "rotation": rotation,
            "layer": layer,
        }

    return result


def update_kicad_pcb_placements(
    kicad_pcb_path: Path | str, placements: dict[str, dict[str, Any]], output_path: Path | str | None = None
) -> dict[str, Any]:
    """Update .kicad_pcb footprint placements from placement dict.

    Uses regex to find and replace (at X Y [ROT]) values within footprint blocks.

    Args:
        kicad_pcb_path: Path to .kicad_pcb file.
        placements: Dict mapping ref → {x, y, rotation, layer}.
        output_path: Write updated file here. If None, dry-run only.

    Returns:
        Dict with {updated: [...], not_found: [...]} lists.
    """
    kicad_pcb_path = Path(kicad_pcb_path)
    content = kicad_pcb_path.read_text(encoding="utf-8")

    updated = []
    not_found = []

    # For each placement, find and replace the footprint's (at ...) clause
    for ref, placement in placements.items():
        x = placement["x"]
        y = placement["y"]
        rotation = placement["rotation"]

        # Find the footprint block for this reference
        # Pattern: (footprint ...) block containing (property "Reference" "REF")
        # Use DOTALL to match across lines, lookahead to end at next footprint or EOF
        ref_pattern = (
            rf'\(footprint\s+"[^"]*".*?\(property\s+"Reference"\s+"{re.escape(ref)}"'
            r".*?(?=\(footprint|$)"
        )
        match = re.search(ref_pattern, content, re.DOTALL)

        if match:
            # Found the footprint block. Now replace (at ...) within ONLY this block
            # to avoid duplicating edits if similar text appears elsewhere.
            footprint_start = match.start()
            footprint_block = match.group(0)

            # Replace (at ...) in this block with the new placement
            new_at_clause = f"(at {x} {y} {rotation})"
            updated_block = re.sub(r"\(at\s+[^)]+\)", new_at_clause, footprint_block, count=1)

            # Replace in content using string slicing to avoid duplicate replacements
            # if the same block text appears multiple times
            before = content[:footprint_start]
            after = content[footprint_start + len(footprint_block) :]
            content = before + updated_block + after

            updated.append(ref)
        else:
            not_found.append(ref)

    # Write output if requested
    if output_path:
        output_path = Path(output_path)
        output_path.write_text(content, encoding="utf-8")

    return {"updated": updated, "not_found": not_found}


def update_cpl_placements(
    cpl_path: Path | str, placements: dict[str, dict[str, Any]], output_path: Path | str | None = None
) -> int:
    """Update CPL (centroid/placement) CSV file with new placements.

    CPL format: Designator,Mid X,Mid Y,Rotation,Layer

    Args:
        cpl_path: Path to CPL CSV file.
        placements: Dict mapping ref → {x, y, rotation, layer}.
        output_path: Write updated file here. If None, dry-run only.

    Returns:
        Count of updated rows.
    """
    cpl_path = Path(cpl_path)
    rows = []
    updated_count = 0

    with open(cpl_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        headers = reader.fieldnames or []

        for row in reader:
            ref = row.get("Designator", "") or row.get("RefDes", "")
            if ref in placements:
                placement = placements[ref]
                row["Mid X"] = str(placement["x"])
                row["Mid Y"] = str(placement["y"])
                row["Rotation"] = str(placement["rotation"])
                if "Layer" in row:
                    row["Layer"] = placement.get("layer", "Front")
                updated_count += 1
            rows.append(row)

    # Write output if requested
    if output_path:
        output_path = Path(output_path)
        with open(output_path, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=headers)
            writer.writeheader()
            writer.writerows(rows)

    return updated_count
