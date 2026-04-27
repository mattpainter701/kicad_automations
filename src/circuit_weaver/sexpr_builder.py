"""S-expression utility functions for KiCad schematic generation.

Extracted from ``generator.py`` (Sprint 44 T188 refactor). Pure functions
for normalizing symbol coordinates and validating S-expression balance.
No dependency on generator state (SheetLayout, allocator, placer, etc.).

Usage:
    from .sexpr_builder import (
        clean_symbol_properties,
        normalize_symbol_property_x,
        adjust_symbol_y_coordinates,
        normalize_symbol_all_coordinates,
        validate_sexpr_balance,
    )
"""

from __future__ import annotations

import logging
import re

_logger = logging.getLogger(__name__)


def clean_symbol_properties(sym_sexpr: str) -> str:
    """Remove vendor-specific properties with out-of-bounds coordinates.

    Properties like "Arrow Part Number", "Arrow Price/Stock", etc. often have
    coordinates with extreme negative values (e.g. -994.92) that cause content
    to spill above the page boundary when the symbol is placed on a sheet.

    Removes property blocks with Y < 0 or Y > 400 mm. Properties with Y < 0
    are almost certainly vendor metadata.
    """
    lines = sym_sexpr.split("\n")
    filtered = []
    i = 0

    while i < len(lines):
        line = lines[i]

        if "(property " in line:
            at_match = re.search(r"\(at\s+([-\d.]+)\s+([-\d.]+)", line)
            if at_match:
                y = float(at_match.group(2))
                if y < 0 or y > 400:
                    paren_count = line.count("(") - line.count(")")
                    i += 1
                    while i < len(lines) and paren_count > 0:
                        paren_count += lines[i].count("(") - lines[i].count(")")
                        i += 1
                    continue

        filtered.append(line)
        i += 1

    return "\n".join(filtered)


def normalize_symbol_property_x(sym_sexpr: str) -> str:
    """Normalize property X coordinates to 0 in symbol definitions.

    All properties in symbol lib_symbols should have X=0 (properties are
    displayed relative to the symbol origin, not at absolute screen coords).
    """
    def fix_property_x(m):
        key, rest, y, angle = m.group(1), m.group(2), m.group(3), m.group(4)
        return f'(property "{key}"{rest}(at 0 {y} {angle})'

    pattern = r'\(property\s+"([^"]+)"([^(]*)\(at\s+[-\d.]+\s+([-\d.]+)\s+(\d+)\)'
    return re.sub(pattern, fix_property_x, sym_sexpr)


def adjust_symbol_y_coordinates(sym_sexpr: str) -> str:
    """Adjust symbol Y coordinates so the minimum Y is >= 0.

    Ensures that when a symbol is placed at Y >= 0 on a sheet,
    all its geometry has Y >= 0.
    """
    lines = sym_sexpr.split("\n")

    y_values: list[float] = []
    at_pattern = re.compile(r"\(at\s+[\d.-]+\s+([\d.-]+)")
    for line in lines:
        for match in at_pattern.finditer(line):
            y_values.append(float(match.group(1)))

    rect_pattern = re.compile(
        r"\(rectangle\s+\(start\s+[\d.-]+\s+([\d.-]+)\)\s+\(end\s+[\d.-]+\s+([\d.-]+)\)"
    )
    for line in lines:
        for match in rect_pattern.finditer(line):
            y_values.append(float(match.group(1)))
            y_values.append(float(match.group(2)))

    if not y_values:
        return sym_sexpr

    min_y = min(y_values)
    if min_y >= 0:
        return sym_sexpr

    y_offset = -min_y
    adjusted_lines = []

    for line in lines:
        def adjust_at(m):
            x, y, rest = m.group(1), float(m.group(2)), m.group(3)
            return f"(at {x} {y + y_offset:.2f}{rest}"

        adjusted = re.sub(r"\(at\s+([\d.-]+)\s+([\d.-]+)(\s+\d+)?", adjust_at, line)

        adjusted = re.sub(
            r"\(rectangle\s+\(start\s+([\d.-]+)\s+([\d.-]+)\)\s+\(end\s+([\d.-]+)\s+([\d.-]+)\)",
            lambda m: (
                f"(rectangle (start {m.group(1)} {float(m.group(2)) + y_offset:.2f}) "
                f"(end {m.group(3)} {float(m.group(4)) + y_offset:.2f})"
            ),
            adjusted,
        )

        adjusted_lines.append(adjusted)

    return "\n".join(adjusted_lines)


def normalize_symbol_all_coordinates(sym_sexpr: str) -> str:
    """Normalize ALL coordinates in a symbol to be relative (centered at origin).

    Handles extracted symbols with absolute coordinates in:
    - Properties: (at X Y angle) → (at 0 Y angle)
    - Pins: (at X Y angle) → (at 0 Y angle)
    - Polylines: (xy X Y) → relative
    - Rectangles: (start X Y) (end X Y) → relative
    """
    lines = sym_sexpr.split("\n")

    all_coords: list[tuple[float, float]] = []

    for line in lines:
        at_matches = re.findall(r"\(at\s+([\d.-]+)\s+([\d.-]+)", line)
        for x, y in at_matches:
            all_coords.append((float(x), float(y)))

        xy_matches = re.findall(r"\(xy\s+([\d.-]+)\s+([\d.-]+)\)", line)
        for x, y in xy_matches:
            all_coords.append((float(x), float(y)))

        rect_matches = re.findall(
            r"\(rectangle\s+\(start\s+([\d.-]+)\s+([\d.-]+)\)\s+\(end\s+([\d.-]+)\s+([\d.-]+)\)",
            line,
        )
        for x1, y1, x2, y2 in rect_matches:
            all_coords.append((float(x1), float(y1)))
            all_coords.append((float(x2), float(y2)))

    if not all_coords:
        return sym_sexpr

    min_x = min(x for x, _ in all_coords)
    min_y = min(y for _, y in all_coords)

    if min_x >= 0 and min_y >= 0:
        return sym_sexpr

    adjusted_lines = []
    for line in lines:
        def shift_at(m):
            x, y, rest = m.group(1), m.group(2), m.group(3)
            return f"(at {float(x) - min_x:.2f} {float(y) - min_y:.2f}{rest}"

        def shift_xy(m):
            return f"(xy {float(m.group(1)) - min_x:.2f} {float(m.group(2)) - min_y:.2f})"

        def shift_rect(m):
            return (
                f"(rectangle (start {float(m.group(1)) - min_x:.2f} {float(m.group(2)) - min_y:.2f}) "
                f"(end {float(m.group(3)) - min_x:.2f} {float(m.group(4)) - min_y:.2f})"
            )

        adjusted = re.sub(r"\(at\s+([\d.-]+)\s+([\d.-]+)(\s+\d+)?", shift_at, line)
        adjusted = re.sub(r"\(xy\s+([\d.-]+)\s+([\d.-]+)\)", shift_xy, adjusted)
        adjusted = re.sub(
            r"\(rectangle\s+\(start\s+([\d.-]+)\s+([\d.-]+)\)\s+\(end\s+([\d.-]+)\s+([\d.-]+)\)",
            shift_rect,
            adjusted,
        )
        adjusted_lines.append(adjusted)

    return "\n".join(adjusted_lines)


_RENDER_SYMBOL_NAME_AND_SEXPR_LUT: dict[str, str] = {}


def render_symbol_name_and_sexpr(comp, comp_key: str) -> tuple[str, str]:
    """Render a component's symbol name and normalized S-expression.

    Extracted from generator for reuse. Uses a module-level LUT to avoid
    re-processing the same (mpn, footprint) pair across multiple instances.
    """
    from .component_db import RENDER_SYMBOL_NAME_AND_SEXPR_LUT as lut

    if comp_key in lut:
        return lut[comp_key]

    # Derive symbol name — prefer value, then mpn, then a generic
    raw = (comp.source_value or comp.value or comp.mpn or "UNKNOWN").strip()
    sym_name = re.sub(r"[^A-Za-z0-9_\-]", "_", raw)

    # Build symbol S-expression from the component
    sym_sexpr = (
        f'    (symbol "{sym_name}" (pin_names hide) (in_bom yes) (on_board yes)\n'
        f'      (property "Reference" "{comp.source_ref or comp.ref_prefix or "?"}" (at 0 0 0)\n'
        f"        (effects (font (size 1.27 1.27)))\n"
        f"      )\n"
        f'      (property "Value" "{raw}" (at 0 0 0)\n'
        f"        (effects (font (size 1.27 1.27)))\n"
        f"      )\n"
        f'      (property "Footprint" "{comp.footprint or ""}" (at 0 0 0)\n'
        f"        (effects (font (size 1.27 1.27)) hide)\n"
        f"      )\n"
    )
    for p in comp.pins:
        pname = (p.name or p.number or "").strip()
        ptype = _pin_type_to_kicad(p.electrical_type)
        pside = _pin_side_to_kicad(p.side, p.electrical_type)
        sym_sexpr += (
            f'      (pin {ptype} {pside} (at 0 0 0) (length 0)\n'
            f'        (name "{pname}" (effects (font (size 1.27 1.27))))\n'
            f'        (number "{p.number}" (effects (font (size 1.27 1.27))))\n'
            f"      )\n"
        )
    sym_sexpr += "    )\n"

    lut[comp_key] = (sym_name, sym_sexpr)
    return sym_name, sym_sexpr


def _pin_type_to_kicad(ptype: str) -> str:
    """Map internal pin type to KiCad pin electrical type keyword."""
    mapping = {
        "input": "input",
        "output": "output",
        "bidirectional": "bidirectional",
        "tri_state": "tri_state",
        "passive": "passive",
        "power_in": "power_in",
        "power_out": "power_out",
        "open_collector": "open_collector",
        "open_emitter": "open_emitter",
        "unconnected": "unconnected",
    }
    return mapping.get(ptype, "passive")


def _pin_side_to_kicad(side: str, ptype: str) -> str:
    """Map internal pin side to KiCad pin graphical style."""
    side_map = {"L": "left", "R": "right", "T": "top", "B": "bottom"}
    return side_map.get(side, "right")


def validate_sexpr_balance(content: str, filename: str) -> bool:
    """Warn if parentheses are unbalanced in a generated S-expression file.

    Counts only parens outside of string literals. Issues a _logger.warning
    rather than raising so generation still proceeds.
    """
    depth = 0
    min_depth = 0
    in_string = False
    escape_next = False
    for ch in content:
        if escape_next:
            escape_next = False
            continue
        if ch == "\\" and in_string:
            escape_next = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            min_depth = min(min_depth, depth)

    valid = depth == 0 and min_depth >= 0 and not in_string
    if not valid:
        _logger.warning(
            "S-expression balance check FAILED for %s: depth=%d, min_depth=%d, in_string=%s",
            filename,
            depth,
            min_depth,
            in_string,
        )
    return valid
