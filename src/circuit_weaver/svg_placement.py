"""SVG placement editor — bidirectional conversion for PCB placement data.

Exports PCB component placements as an SVG diagram that users can edit in
Inkscape/CorelDRAW, then imports the edited SVG back to update KiCad .kicad_pcb
and CPL files.

The update_kicad_pcb_placements() function uses the official KiCad Python API
(pcbnew) when available (KiCad 6+), with automatic fallback to regex-based
updates if KiCad is not installed or the API is unavailable.

Usage:
    from circuit_weaver.svg_placement import export_placement_svg, import_placement_from_svg
    from circuit_weaver.kicad_placement_api import check_kicad_available

    # Check if KiCad API is available
    available, msg = check_kicad_available()
    if not available:
        print(f"Warning: KiCad not available. {msg}")

    # Export placement to SVG
    svg_path = export_placement_svg(components, placements, 100, 80, output_path="placement.svg")

    # User edits SVG in Inkscape...

    # Import edited SVG back
    updated_placements = import_placement_from_svg("placement.svg")
    result = update_kicad_pcb_placements(
        "design.kicad_pcb",
        updated_placements,
        output_path="design.kicad_pcb",
        use_api=True  # Use KiCad API if available, fallback to regex
    )
    print(result["message"])
"""

from __future__ import annotations

import csv
import logging
import math
import re
import uuid
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

from .placement_optimizer import estimate_footprint_size

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
    "placeholder": "#D946EF",
    "misc": "#CCCCCC",
}

ET.register_namespace("", _SVG_NS)


def _get_component_size(component: dict[str, Any]) -> tuple[float, float]:
    """Use explicit optimizer geometry or the shared footprint estimator."""
    width = component.get("width_mm")
    height = component.get("height_mm")
    if all(
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
        and float(value) > 0
        for value in (width, height)
    ):
        return (float(width), float(height))
    return estimate_footprint_size(
        str(component.get("footprint", "") or ""),
        str(component.get("ref", "") or ""),
    )


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
    _board_outline = ET.SubElement(
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

        opacity = "0.5" if layer == "back" else ("0.65" if category == "placeholder" else "1")
        stroke_dasharray = (
            "2 2" if category == "placeholder" else ("4 2" if layer == "back" else "none")
        )

        _rect = ET.SubElement(
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
                # The component group carries the physical footprint rotation.
                # Counter-rotate only the label so reference designators remain
                # readable while the group's transform stays authoritative for
                # round-trip placement import.
                "transform": f"rotate({-float(rotation):g})",
            },
        )
        text.text = ref

    # Convert to string
    _tree = ET.ElementTree(svg)
    svg_str = ET.tostring(svg, encoding="unicode", method="xml")

    # Write to file if requested
    if output_path:
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(f'<?xml version="1.0"?>\n{svg_str}', encoding="utf-8")

    return svg_str


def _parse_transform_legacy(transform_str: str) -> tuple[float, float, float]:
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
                    a, b, _, _, e, f = parts[0], parts[1], parts[2], parts[3], parts[4], parts[5]
                    x_px = e  # translation x
                    y_px = f  # translation y
                    rotation = math.degrees(math.atan2(b, a))  # rotation in degrees
    except (ValueError, AttributeError, IndexError) as exc:
        # Gracefully degrade to defaults on parse error
        logging.debug("Failed to parse SVG transform %r: %s", transform_str, exc)

    return x_px, y_px, rotation


_TRANSFORM_RE = re.compile(r"([A-Za-z]+)\s*\(([^)]*)\)")


def _multiply_affine(
    left: tuple[float, float, float, float, float, float],
    right: tuple[float, float, float, float, float, float],
) -> tuple[float, float, float, float, float, float]:
    la, lb, lc, ld, le, lf = left
    ra, rb, rc, rd, re_, rf = right
    return (
        la * ra + lc * rb,
        lb * ra + ld * rb,
        la * rc + lc * rd,
        lb * rc + ld * rd,
        la * re_ + lc * rf + le,
        lb * re_ + ld * rf + lf,
    )


def _parse_transform_matrix(transform_str: str) -> tuple[float, float, float, float, float, float]:
    """Parse a strict SVG transform list into one affine matrix."""
    value = (transform_str or "").strip()
    if not value:
        raise ValueError("Component SVG group is missing a transform")
    current = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
    cursor = 0
    matched = False
    for match in _TRANSFORM_RE.finditer(value):
        if value[cursor : match.start()].strip(" ,\t\r\n"):
            raise ValueError(f"Unsupported SVG transform syntax: {transform_str!r}")
        cursor = match.end()
        matched = True
        name = match.group(1).lower()
        raw_args = [part for part in re.split(r"[\s,]+", match.group(2).strip()) if part]
        try:
            args = [float(part) for part in raw_args]
        except ValueError as exc:
            raise ValueError(f"Invalid numeric SVG transform: {transform_str!r}") from exc
        if not all(math.isfinite(number) for number in args):
            raise ValueError(f"Non-finite SVG transform: {transform_str!r}")

        if name == "matrix" and len(args) == 6:
            local = (args[0], args[1], args[2], args[3], args[4], args[5])
        elif name == "translate" and len(args) in {1, 2}:
            local = (1.0, 0.0, 0.0, 1.0, args[0], args[1] if len(args) == 2 else 0.0)
        elif name == "scale" and len(args) in {1, 2}:
            local = (args[0], 0.0, 0.0, args[1] if len(args) == 2 else args[0], 0.0, 0.0)
        elif name == "rotate" and len(args) in {1, 3}:
            radians = math.radians(args[0])
            cosine, sine = math.cos(radians), math.sin(radians)
            rotation = (cosine, sine, -sine, cosine, 0.0, 0.0)
            if len(args) == 3:
                cx, cy = args[1], args[2]
                local = _multiply_affine(
                    _multiply_affine((1.0, 0.0, 0.0, 1.0, cx, cy), rotation),
                    (1.0, 0.0, 0.0, 1.0, -cx, -cy),
                )
            else:
                local = rotation
        else:
            raise ValueError(f"Unsupported SVG transform {name}({match.group(2)})")
        current = _multiply_affine(current, local)

    if not matched or value[cursor:].strip(" ,\t\r\n"):
        raise ValueError(f"Unsupported SVG transform syntax: {transform_str!r}")
    return current


def _placement_from_matrix(
    matrix: tuple[float, float, float, float, float, float],
) -> tuple[float, float, float]:
    a, b, c, d, e, f = matrix
    determinant = a * d - b * c
    scale_x = math.hypot(a, b)
    scale_y = math.hypot(c, d)
    orthogonality = abs(a * c + b * d)
    if determinant <= 0 or scale_x <= 1e-12 or scale_y <= 1e-12:
        raise ValueError("SVG placement transform is mirrored or singular")
    if orthogonality > 1e-6 * max(1.0, scale_x * scale_y):
        raise ValueError("Skewed SVG placement transforms are not supported")
    return e, f, math.degrees(math.atan2(b, a)) % 360.0


def _parse_transform(transform_str: str) -> tuple[float, float, float]:
    """Parse one strict SVG transform list into translation and rotation."""
    return _placement_from_matrix(_parse_transform_matrix(transform_str))


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

    if not math.isfinite(scale) or scale <= 0:
        raise ValueError(f"Invalid SVG placement scale: {scale_str!r}")

    result: dict[str, dict[str, Any]] = {}

    def walk(element, parent_matrix, inherited_transform: bool = False):
        ref = element.get("data-ref")
        if not ref and not any(descendant.get("data-ref") for descendant in element.iter()):
            return
        local = parent_matrix
        transform = element.get("transform", "")
        if transform:
            local = _multiply_affine(parent_matrix, _parse_transform_matrix(transform))
        has_transform = inherited_transform or bool(transform)
        if ref and (known_refs is None or ref in known_refs):
            if not has_transform:
                raise ValueError(f"Component {ref} has no placement transform")
            if ref in result:
                raise ValueError(f"Duplicate component reference in placement SVG: {ref}")
            x_px, y_px, rotation = _placement_from_matrix(local)
            layer = element.get("data-layer", "front")
            if layer not in {"front", "back", "top", "bottom"}:
                raise ValueError(f"Invalid placement layer for {ref}: {layer!r}")
            result[ref] = {
                "x": round(x_px / scale, 3),
                "y": round(y_px / scale, 3),
                "rotation": rotation,
                "layer": layer,
            }
        for child in element:
            walk(child, local, has_transform)

    walk(root, (1.0, 0.0, 0.0, 1.0, 0.0, 0.0))

    return result


def update_kicad_pcb_placements(
    kicad_pcb_path: Path | str,
    placements: dict[str, dict[str, Any]],
    output_path: Path | str | None = None,
    use_api: bool = True,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Update .kicad_pcb footprint placements from placement dict.

    Prefers KiCad Python API (pcbnew) for robustness, falls back to regex if unavailable.

    Args:
        kicad_pcb_path: Path to .kicad_pcb file.
        placements: Dict mapping ref → {x, y, rotation, layer}.
        output_path: Write updated file here. If None, dry-run only.
        use_api: If True (default), try KiCad API first; fallback to regex if unavailable.

    Returns:
        Dict with {success: bool, updated: [...], not_found: [...], errors: [...], message: str}.
    """
    kicad_pcb_path = Path(kicad_pcb_path)

    # Try KiCad API first if enabled
    if use_api:
        from .kicad_placement_api import update_board_placements

        result = update_board_placements(
            kicad_pcb_path,
            placements,
            output_path=Path(output_path) if output_path else None,
            dry_run=dry_run,
        )
        return result

    # Fallback: regex-based approach
    try:
        content = kicad_pcb_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {
            "success": False,
            "updated": [],
            "not_found": list(placements.keys()),
            "errors": [f"File not found: {kicad_pcb_path}"],
            "message": f"Could not read {kicad_pcb_path}",
        }
    except Exception as e:
        return {
            "success": False,
            "updated": [],
            "not_found": list(placements.keys()),
            "errors": [str(e)],
            "message": f"Error reading file: {e}",
        }

    def footprint_spans(text: str):
        cursor = 0
        while True:
            start = text.find("(footprint", cursor)
            if start < 0:
                return
            depth = 0
            quoted = False
            escaped = False
            for index in range(start, len(text)):
                char = text[index]
                if escaped:
                    escaped = False
                elif quoted and char == "\\":
                    escaped = True
                elif char == '"':
                    quoted = not quoted
                elif not quoted and char == "(":
                    depth += 1
                elif not quoted and char == ")":
                    depth -= 1
                    if depth == 0:
                        yield start, index + 1, text[start : index + 1]
                        cursor = index + 1
                        break
            else:
                raise ValueError("KiCad PCB contains an unterminated footprint block")

    by_ref: dict[str, tuple[int, int, str]] = {}
    for start, end, block in footprint_spans(content):
        match = re.search(r'\(property\s+"Reference"\s+"([^"]+)"', block)
        if match is None:
            match = re.search(r'\(fp_text\s+reference\s+"([^"]+)"', block)
        if match is None:
            continue
        ref = match.group(1)
        if ref in by_ref:
            return {
                "success": False,
                "updated": [],
                "not_found": [],
                "errors": [f"Duplicate PCB footprint reference: {ref}"],
                "message": "PCB reference reconciliation failed",
            }
        by_ref[ref] = (start, end, block)

    not_found = sorted(set(placements) - set(by_ref))
    errors: list[str] = []
    replacements: list[tuple[int, int, str, str]] = []
    for ref, placement in placements.items():
        if ref not in by_ref:
            continue
        start, end, block = by_ref[ref]
        layer_match = re.search(r'\(layer\s+"([FB]\.Cu)"\)', block)
        if layer_match is None:
            errors.append(f"{ref}: footprint has no F.Cu/B.Cu layer")
            continue
        current_layer = "back" if layer_match.group(1) == "B.Cu" else "front"
        requested_layer = str(placement.get("layer", "front")).lower()
        requested_layer = "back" if requested_layer in {"back", "bottom"} else (
            "front" if requested_layer in {"front", "top"} else ""
        )
        if not requested_layer:
            errors.append(f"{ref}: invalid requested layer {placement.get('layer')!r}")
            continue
        if requested_layer != current_layer:
            errors.append(
                f"{ref}: regex fallback cannot safely flip {current_layer} to {requested_layer}; use pcbnew"
            )
            continue
        try:
            x = float(placement["x"])
            y = float(placement["y"])
            rotation = float(placement.get("rotation", 0.0))
        except (KeyError, TypeError, ValueError) as exc:
            errors.append(f"{ref}: invalid placement values ({exc})")
            continue
        if not all(math.isfinite(value) for value in (x, y, rotation)):
            errors.append(f"{ref}: placement contains non-finite values")
            continue
        updated_block, count = re.subn(
            r"\(at\s+[^)]+\)",
            f"(at {x:g} {y:g} {rotation:g})",
            block,
            count=1,
        )
        if count != 1:
            errors.append(f"{ref}: footprint has no placement (at ...) clause")
            continue
        replacements.append((start, end, updated_block, ref))

    if not_found or errors:
        return {
            "success": False,
            "updated": [],
            "not_found": not_found,
            "errors": errors,
            "message": "Placement update blocked; PCB was not modified",
            "dry_run": dry_run,
        }

    for start, end, updated_block, _ref in sorted(replacements, reverse=True):
        content = content[:start] + updated_block + content[end:]

    destination = Path(output_path) if output_path else kicad_pcb_path
    if not dry_run:
        temporary = destination.with_name(f".{destination.name}.{uuid.uuid4().hex}.tmp")
        try:
            destination.parent.mkdir(parents=True, exist_ok=True)
            temporary.write_text(content, encoding="utf-8")
            temporary.replace(destination)
        except Exception as e:
            temporary.unlink(missing_ok=True)
            return {
                "success": False,
                "updated": [],
                "not_found": [],
                "errors": [f"Error writing output: {e}"],
                "message": f"Could not write to {destination}",
                "dry_run": dry_run,
            }

    return {
        "success": bool(replacements),
        "updated": [replacement[3] for replacement in replacements],
        "not_found": [],
        "errors": [],
        "message": (
            f"Validated {len(replacements)} placement changes (dry run)"
            if dry_run
            else f"Updated {len(replacements)}/{len(placements)} placements (regex fallback)"
        ),
        "dry_run": dry_run,
    }


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
                    requested_layer = str(placement.get("layer", "front")).lower()
                    row["Layer"] = "bottom" if requested_layer in {"back", "bottom"} else "top"
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
