"""Round-trip parser for KiCad .kicad_sch files.

Parses an existing schematic back into structured data that can be
compared against or merged with engine-generated output. Enables
preserve-user-edits workflows: manual position overrides, added
wires, and deleted components survive regeneration.

Usage:
    from circuit_weaver.parser import parse_schematic
    parsed = parse_schematic("path/to/file.kicad_sch")
    print(parsed.components)   # list of ParsedComponent
    print(parsed.wires)        # list of ParsedWire
"""

import re
from dataclasses import dataclass, field
from pathlib import Path

# ================================================================
# Dataclasses
# ================================================================


@dataclass
class ParsedComponent:
    """A placed component instance extracted from a .kicad_sch file."""

    ref: str
    lib_id: str
    value: str
    footprint: str
    x: float
    y: float
    angle: float = 0.0
    properties: dict = field(default_factory=dict)  # name -> value for custom fields
    uuid: str = ""
    unit: int = 1
    dnp: bool = False


@dataclass
class ParsedWire:
    """A wire segment between two points."""

    x1: float
    y1: float
    x2: float
    y2: float
    uuid: str = ""


@dataclass
class ParsedGlobalLabel:
    """A global label placed on the schematic."""

    name: str
    x: float
    y: float
    angle: float = 0.0
    shape: str = "bidirectional"
    uuid: str = ""


@dataclass
class ParsedNoConnect:
    """A no-connect marker."""

    x: float
    y: float
    uuid: str = ""


@dataclass
class TitleBlock:
    """Title block metadata."""

    title: str = ""
    date: str = ""
    rev: str = ""
    company: str = ""
    comments: dict = field(default_factory=dict)  # comment_num -> text


@dataclass
class ParsedSchematic:
    """Complete parsed representation of a .kicad_sch file."""

    components: list[ParsedComponent] = field(default_factory=list)
    wires: list[ParsedWire] = field(default_factory=list)
    global_labels: list[ParsedGlobalLabel] = field(default_factory=list)
    hierarchical_labels: list[ParsedGlobalLabel] = field(default_factory=list)
    no_connects: list[ParsedNoConnect] = field(default_factory=list)
    title_block: TitleBlock = field(default_factory=TitleBlock)
    paper: str = "A3"
    version: str = ""
    generator: str = ""
    file_uuid: str = ""


# ================================================================
# S-expression bracket matching
# ================================================================


def _find_matching_close(text: str, open_pos: int) -> int:
    """Find the index of the closing paren that matches the opening paren at open_pos.

    Returns -1 if no match found.
    """
    depth = 0
    in_string = False
    i = open_pos
    while i < len(text):
        ch = text[i]
        if ch == '"' and (i == 0 or text[i - 1] != "\\"):
            in_string = not in_string
        elif not in_string:
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0:
                    return i
        i += 1
    return -1


def _extract_blocks(text: str, keyword: str) -> list[str]:
    """Extract all top-level S-expression blocks starting with (keyword ...).

    Returns the full text of each block including the outer parens.
    """
    blocks = []
    pattern = re.compile(r"\(" + re.escape(keyword) + r"[\s(]")
    pos = 0
    while pos < len(text):
        m = pattern.search(text, pos)
        if not m:
            break
        start = m.start()
        end = _find_matching_close(text, start)
        if end < 0:
            break
        blocks.append(text[start : end + 1])
        pos = end + 1
    return blocks


# ================================================================
# Parsing helpers
# ================================================================

_RE_QUOTED = re.compile(r'"((?:[^"\\]|\\.)*)"')


def _extract_quoted(text: str, keyword: str) -> str:
    """Extract the first quoted value after (keyword "value" ...)."""
    pattern = re.compile(r"\(" + re.escape(keyword) + r'\s+"((?:[^"\\]|\\.)*)"')
    m = pattern.search(text)
    return m.group(1) if m else ""


def _extract_at(text: str) -> tuple[float, float, float]:
    """Extract (at x y [angle]) from text. Returns (x, y, angle)."""
    m = re.search(r"\(at\s+([-\d.]+)\s+([-\d.]+)(?:\s+([-\d.]+))?\)", text)
    if not m:
        return (0.0, 0.0, 0.0)
    x = float(m.group(1))
    y = float(m.group(2))
    angle = float(m.group(3)) if m.group(3) else 0.0
    return (x, y, angle)


def _extract_uuid(text: str) -> str:
    """Extract the first (uuid "...") value."""
    m = re.search(r'\(uuid\s+"([^"]+)"\)', text)
    return m.group(1) if m else ""


# ================================================================
# Component parser
# ================================================================


def _parse_component(block: str) -> ParsedComponent | None:
    """Parse a placed symbol block into a ParsedComponent."""
    # lib_id
    m_lib = re.search(r'\(lib_id\s+"([^"]+)"\)', block)
    if not m_lib:
        return None
    lib_id = m_lib.group(1)

    # Position: (at x y angle)
    m_at = re.search(r'\(symbol\s+\(lib_id\s+"[^"]+"\)\s+\(at\s+([-\d.]+)\s+([-\d.]+)(?:\s+([-\d.]+))?\)', block)
    if m_at:
        x = float(m_at.group(1))
        y = float(m_at.group(2))
        angle = float(m_at.group(3)) if m_at.group(3) else 0.0
    else:
        x, y, angle = _extract_at(block)

    # Unit
    m_unit = re.search(r"\(unit\s+(\d+)\)", block)
    unit = int(m_unit.group(1)) if m_unit else 1

    # UUID
    uuid_val = _extract_uuid(block)

    # DNP
    dnp = bool(re.search(r"\(dnp\s+yes\)", block))

    # Properties
    properties = {}
    for m_prop in re.finditer(
        r'\(property\s+"([^"]+)"\s+"((?:[^"\\]|\\.)*)"',
        block,
    ):
        prop_name = m_prop.group(1)
        prop_value = m_prop.group(2)
        properties[prop_name] = prop_value

    ref = properties.get("Reference", "")
    value = properties.get("Value", "")
    footprint = properties.get("Footprint", "")

    # Build custom properties dict (exclude the standard ones)
    standard_props = {"Reference", "Value", "Footprint", "Datasheet", "Intersheetref"}
    custom_props = {k: v for k, v in properties.items() if k not in standard_props}

    return ParsedComponent(
        ref=ref,
        lib_id=lib_id,
        value=value,
        footprint=footprint,
        x=x,
        y=y,
        angle=angle,
        properties=custom_props,
        uuid=uuid_val,
        unit=unit,
        dnp=dnp,
    )


# ================================================================
# Wire parser
# ================================================================

_RE_WIRE = re.compile(
    r"\(wire\s+\(pts\s+\(xy\s+([-\d.]+)\s+([-\d.]+)\)\s+\(xy\s+([-\d.]+)\s+([-\d.]+)\)\)",
    re.DOTALL,
)


def _parse_wires(text: str) -> list[ParsedWire]:
    """Parse all wire blocks from schematic text."""
    wires = []
    for block in _extract_blocks(text, "wire"):
        m = _RE_WIRE.search(block)
        if m:
            wires.append(
                ParsedWire(
                    x1=float(m.group(1)),
                    y1=float(m.group(2)),
                    x2=float(m.group(3)),
                    y2=float(m.group(4)),
                    uuid=_extract_uuid(block),
                )
            )
    return wires


# ================================================================
# Global label parser
# ================================================================

_RE_GLOBAL_LABEL = re.compile(
    r'\(global_label\s+"([^"]+)"\s+\(shape\s+(\w+)\)\s+\(at\s+([-\d.]+)\s+([-\d.]+)(?:\s+([-\d.]+))?\)',
)
_RE_HIERARCHICAL_LABEL = re.compile(
    r'\(hierarchical_label\s+"([^"]+)"\s+\(shape\s+(\w+)\)\s+\(at\s+([-\d.]+)\s+([-\d.]+)(?:\s+([-\d.]+))?\)',
)


def _parse_global_labels(text: str) -> list[ParsedGlobalLabel]:
    """Parse all global label blocks from schematic text."""
    labels = []
    for block in _extract_blocks(text, "global_label"):
        m = _RE_GLOBAL_LABEL.search(block)
        if m:
            labels.append(
                ParsedGlobalLabel(
                    name=m.group(1),
                    x=float(m.group(3)),
                    y=float(m.group(4)),
                    angle=float(m.group(5)) if m.group(5) else 0.0,
                    shape=m.group(2),
                    uuid=_extract_uuid(block),
                )
            )
    return labels


def _parse_hierarchical_labels(text: str) -> list[ParsedGlobalLabel]:
    """Parse all hierarchical label blocks from schematic text."""
    labels = []
    for block in _extract_blocks(text, "hierarchical_label"):
        m = _RE_HIERARCHICAL_LABEL.search(block)
        if m:
            labels.append(
                ParsedGlobalLabel(
                    name=m.group(1),
                    x=float(m.group(3)),
                    y=float(m.group(4)),
                    angle=float(m.group(5)) if m.group(5) else 0.0,
                    shape=m.group(2),
                    uuid=_extract_uuid(block),
                )
            )
    return labels


# ================================================================
# No-connect parser
# ================================================================

_RE_NO_CONNECT = re.compile(
    r'\(no_connect\s+\(at\s+([-\d.]+)\s+([-\d.]+)\)\s+\(uuid\s+"([^"]+)"\)\)',
)


def _parse_no_connects(text: str) -> list[ParsedNoConnect]:
    """Parse all no-connect markers from schematic text."""
    ncs = []
    for m in _RE_NO_CONNECT.finditer(text):
        ncs.append(
            ParsedNoConnect(
                x=float(m.group(1)),
                y=float(m.group(2)),
                uuid=m.group(3),
            )
        )
    return ncs


# ================================================================
# Title block parser
# ================================================================


def _parse_title_block(text: str) -> TitleBlock:
    """Parse the title_block section."""
    tb = TitleBlock()
    blocks = _extract_blocks(text, "title_block")
    if not blocks:
        return tb
    block = blocks[0]

    tb.title = _extract_quoted(block, "title")
    tb.date = _extract_quoted(block, "date")
    tb.rev = _extract_quoted(block, "rev")
    tb.company = _extract_quoted(block, "company")

    for m in re.finditer(r'\(comment\s+(\d+)\s+"([^"]*)"', block):
        tb.comments[int(m.group(1))] = m.group(2)

    return tb


# ================================================================
# Main parser
# ================================================================


def parse_schematic(path: str | Path) -> ParsedSchematic:
    """Parse a .kicad_sch file into structured data.

    Args:
        path: Path to the .kicad_sch file.

    Returns:
        ParsedSchematic with all extracted elements.

    Raises:
        FileNotFoundError: If the file does not exist.
        ValueError: If the file is not a valid KiCad schematic.
    """
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(f"Cannot read {path} — file contains invalid UTF-8: {exc}") from exc

    if not text.strip().startswith("(kicad_sch"):
        raise ValueError(f"Not a valid KiCad schematic: {path}")

    parsed = ParsedSchematic()

    # Version and generator
    m_ver = re.search(r"\(version\s+(\d+)\)", text)
    if m_ver:
        parsed.version = m_ver.group(1)

    m_gen = re.search(r'\(generator\s+"([^"]+)"\)', text)
    if m_gen:
        parsed.generator = m_gen.group(1)

    # File UUID (the first uuid in the file, right after the header)
    m_uuid = re.search(r'\(kicad_sch\s+\(version\s+\d+\).*?\(uuid\s+"([^"]+)"\)', text, re.DOTALL)
    if m_uuid:
        parsed.file_uuid = m_uuid.group(1)

    # Paper size
    m_paper = re.search(r'\(paper\s+"([^"]+)"\)', text)
    if m_paper:
        parsed.paper = m_paper.group(1)

    # Title block
    parsed.title_block = _parse_title_block(text)

    # Components — match placed symbol instances (not lib_symbols definitions)
    # We need to find (symbol (lib_id "...") ...) blocks that are NOT inside (lib_symbols ...)
    # Strategy: remove the lib_symbols section, then parse remaining symbol blocks
    stripped = _remove_lib_symbols_section(text)

    for block in _extract_blocks(stripped, "symbol"):
        # Skip if it doesn't have lib_id (it's a lib_symbol definition that leaked through)
        if "(lib_id" not in block:
            continue
        comp = _parse_component(block)
        if comp:
            parsed.components.append(comp)

    # Wires
    parsed.wires = _parse_wires(text)

    # Global labels
    parsed.global_labels = _parse_global_labels(text)
    parsed.hierarchical_labels = _parse_hierarchical_labels(text)

    # No-connects
    parsed.no_connects = _parse_no_connects(text)

    return parsed


def _remove_lib_symbols_section(text: str) -> str:
    """Remove the (lib_symbols ...) section.

    Prevents parsing library definitions as placed components.
    """
    m = re.search(r"\(lib_symbols\b", text)
    if not m:
        return text
    start = m.start()
    end = _find_matching_close(text, start)
    if end < 0:
        return text
    return text[:start] + text[end + 1 :]


# ================================================================
# Merge: preserve user edits when regenerating
# ================================================================

# Deletion marker pattern in KiCad text annotations
_DELETED_MARKER_RE = re.compile(r"DELETED:\s*(\w+)")


def _find_deleted_refs(parsed: ParsedSchematic, text: str) -> set[str]:
    """Find refs marked as deleted via text annotations in the schematic.

    Looks for text annotations containing 'DELETED: Uxx' patterns.
    Also checks for (text "<!-- DELETED: U5 -->") style markers.
    """
    deleted = set()
    for m in re.finditer(r'\(text\s+"[^"]*DELETED:\s*(\w+)[^"]*"', text):
        deleted.add(m.group(1))
    return deleted


def merge_with_generated(
    parsed: ParsedSchematic,
    generated_content: str,
    original_text: str = "",
) -> str:
    """Merge a parsed (user-edited) schematic with newly generated content.

    Merge rules:
    1. Position preservation: if a component exists in both parsed and generated
       with the same ref, keep the parsed (user-edited) position.
    2. Wire preservation: manually added wires and labels not in generated output
       are preserved.
    3. Value updates: component values and connections from generated content win.
    4. New components: components in generated but not in parsed are added.
    5. Deleted components: refs that exist in generated but not in parsed AND
       have a DELETED marker in the original text are removed.

    Args:
        parsed: ParsedSchematic from the existing file.
        generated_content: Full .kicad_sch text from the generator.
        original_text: Raw text of the original schematic (for deletion markers).

    Returns:
        Merged .kicad_sch content string.
    """
    # Build lookup of parsed components by ref
    parsed_by_ref = {c.ref: c for c in parsed.components if c.ref}

    # Find deleted refs
    deleted_refs = _find_deleted_refs(parsed, original_text)

    # Parse the generated content to get generated components
    gen_stripped = _remove_lib_symbols_section(generated_content)
    gen_components = {}
    for block in _extract_blocks(gen_stripped, "symbol"):
        if "(lib_id" not in block:
            continue
        comp = _parse_component(block)
        if comp and comp.ref:
            gen_components[comp.ref] = block

    # Build set of generated wire signatures for deduplication
    gen_wires = set()
    for w in _parse_wires(generated_content):
        sig = _wire_signature(w.x1, w.y1, w.x2, w.y2)
        gen_wires.add(sig)

    # Build set of generated label signatures
    gen_labels = set()
    for lbl in _parse_global_labels(generated_content):
        gen_labels.add((lbl.name, round(lbl.x, 2), round(lbl.y, 2)))
    gen_hier_labels = set()
    for lbl in _parse_hierarchical_labels(generated_content):
        gen_hier_labels.add((lbl.name, round(lbl.x, 2), round(lbl.y, 2)))

    # Start building merged output from generated content
    result = generated_content

    # Step 1: Apply position overrides from parsed to generated
    for ref, parsed_comp in parsed_by_ref.items():
        if ref in gen_components and ref not in deleted_refs:
            result = _apply_position_override(result, ref, parsed_comp)

    # Step 2: Remove components that user deleted
    for ref in deleted_refs:
        if ref in gen_components:
            result = _remove_component_block(result, ref)

    # Step 3: Preserve manually added wires not in generated
    extra_wires = []
    for w in parsed.wires:
        sig = _wire_signature(w.x1, w.y1, w.x2, w.y2)
        if sig not in gen_wires:
            extra_wires.append(
                f"  (wire (pts (xy {w.x1:.2f} {w.y1:.2f}) (xy {w.x2:.2f} {w.y2:.2f}))\n"
                f"    (stroke (width 0) (type default))\n"
                f'    (uuid "{w.uuid}")\n'
                f"  )\n"
            )

    # Step 4: Preserve manually added labels not in generated
    extra_labels = []
    for lbl in parsed.global_labels:
        sig = (lbl.name, round(lbl.x, 2), round(lbl.y, 2))
        if sig not in gen_labels:
            extra_labels.append(_format_preserved_label("global_label", lbl))
    for lbl in parsed.hierarchical_labels:
        sig = (lbl.name, round(lbl.x, 2), round(lbl.y, 2))
        if sig not in gen_hier_labels:
            extra_labels.append(_format_preserved_label("hierarchical_label", lbl))

    # Insert extra wires and labels before the closing paren
    if extra_wires or extra_labels:
        extras = "\n".join(extra_wires) + "\n".join(extra_labels)
        # Insert before the final closing paren
        last_close = result.rfind(")")
        if last_close >= 0:
            result = result[:last_close] + extras + "\n" + result[last_close:]

    return result


def _format_preserved_label(keyword: str, lbl: ParsedGlobalLabel) -> str:
    """Render a preserved global/hierarchical label block back to KiCad text."""
    angle_str = f" {lbl.angle:.0f}" if lbl.angle != 0 else " 0"
    at_str = f"(at {lbl.x:.2f} {lbl.y:.2f}{angle_str})"
    return (
        f'  ({keyword} "{lbl.name}" (shape {lbl.shape}) {at_str}\n'
        f"    (effects (font (size 1.0 1.0)))\n"
        f'    (uuid "{lbl.uuid}")\n'
        f'    (property "Intersheetref" "${{INTERSHEET_REFS}}" (at 0 0 0)\n'
        f"      (effects (font (size 1.0 1.0)) hide)\n"
        f"    )\n"
        f"  )\n"
    )


def _wire_signature(x1: float, y1: float, x2: float, y2: float) -> tuple:
    """Create a canonical signature for a wire segment (order-independent)."""
    p1 = (round(x1, 2), round(y1, 2))
    p2 = (round(x2, 2), round(y2, 2))
    return tuple(sorted([p1, p2]))


def _apply_position_override(content: str, ref: str, parsed_comp: ParsedComponent) -> str:
    """Override a component's position in generated content with parsed position.

    Finds the placed symbol block for the given ref and replaces its (at x y angle).
    """
    # Find the symbol block containing this ref
    # Pattern: (symbol (lib_id "...") (at X Y A) ... (property "Reference" "ref" ...)
    # We need to find the (at ...) in the same symbol block as this ref

    # Strategy: find all symbol blocks, identify the one with this ref, replace its at
    pattern = re.compile(
        r'(\(symbol\s+\(lib_id\s+"[^"]+"\)\s+\(at\s+)([-\d.]+)(\s+)([-\d.]+)(\s+)([-\d.]+)(\))',
    )

    # We need to identify which match corresponds to this ref.
    # Walk through the content finding symbol blocks
    result_parts = []
    last_end = 0

    for m_at in pattern.finditer(content):
        # Check if this symbol block contains this ref
        block_start = m_at.start()
        block_end = _find_matching_close(content, block_start)
        if block_end < 0:
            continue
        block_text = content[block_start : block_end + 1]

        # Check if this block has the right Reference property
        ref_match = re.search(r'\(property\s+"Reference"\s+"' + re.escape(ref) + r'"', block_text)
        if not ref_match:
            continue

        # Compute position delta for property text relocation
        old_x = float(m_at.group(2))
        old_y = float(m_at.group(4))
        dx = parsed_comp.x - old_x
        dy = parsed_comp.y - old_y

        # Replace the whole block with position-adjusted version
        new_block = block_text
        # 1. Update symbol (at ...)
        new_block = re.sub(
            r'(\(symbol\s+\(lib_id\s+"[^"]+"\)\s+\(at\s+)([-\d.]+)(\s+)([-\d.]+)(\s+)([-\d.]+)(\))',
            lambda m: (
                f"{m.group(1)}{parsed_comp.x:.2f}{m.group(3)}"
                f"{parsed_comp.y:.2f}{m.group(5)}{parsed_comp.angle:.0f}{m.group(7)}"
            ),
            new_block,
            count=1,
        )

        # 2. Shift all property (at ...) coordinates by the same delta
        prop_at_pattern = re.compile(r'(\(property\s+"[^"]*"\s+"[^"]*"\s+\(at\s+)([-\d.]+)(\s+)([-\d.]+)(\s+[-\d.]+\))')
        new_block = prop_at_pattern.sub(
            lambda pm: (
                f"{pm.group(1)}{float(pm.group(2)) + dx:.2f}{pm.group(3)}{float(pm.group(4)) + dy:.2f}{pm.group(5)}"
            ),
            new_block,
        )

        result_parts.append(content[last_end:block_start])
        result_parts.append(new_block)
        last_end = block_end + 1
        break  # Only one symbol per ref

    if result_parts:
        result_parts.append(content[last_end:])
        return "".join(result_parts)
    return content


def _remove_component_block(content: str, ref: str) -> str:
    """Remove a placed symbol block for a given ref from content."""
    # Find symbol blocks containing this ref
    pattern = re.compile(r'\(symbol\s+\(lib_id\s+"[^"]+"\)')
    pos = 0
    while pos < len(content):
        m = pattern.search(content, pos)
        if not m:
            break
        block_start = m.start()
        block_end = _find_matching_close(content, block_start)
        if block_end < 0:
            break
        block_text = content[block_start : block_end + 1]

        # Check if this block has the matching ref
        ref_match = re.search(
            r'\(property\s+"Reference"\s+"' + re.escape(ref) + r'"',
            block_text,
        )
        if ref_match:
            # Remove this block (including surrounding whitespace)
            # Find start of line
            line_start = content.rfind("\n", 0, block_start)
            line_start = line_start + 1 if line_start >= 0 else block_start
            # Find end of line after block
            line_end = content.find("\n", block_end)
            line_end = line_end + 1 if line_end >= 0 else block_end + 1
            content = content[:line_start] + content[line_end:]
            break  # Only one symbol per ref
        pos = block_end + 1

    return content
