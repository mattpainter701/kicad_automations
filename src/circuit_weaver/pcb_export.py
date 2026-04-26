"""PCB placement hint generator — creates a .kicad_pcb with approximate footprint positions.

Generates a minimal KiCad PCB file containing:
- Board outline (rectangular, auto-sized with margins)
- Footprints placed by functional category (power top-left, digital center, connectors edges)
- Net class definitions derived from net naming conventions
- Net declarations for all component signal and power nets

This is a placement *hint* file, not a routed PCB. Use it as a starting point
for manual routing in KiCad.

Usage:
    from circuit_weaver.pcb_export import generate_pcb_placement
    generate_pcb_placement(components, output_path, "MyBoard")
"""

import logging
import re
from pathlib import Path

from .component_db import ComponentDef

_logger = logging.getLogger(__name__)

# KiCad 10 validates fixed layers against canonical ids/names when loading a
# board. The older KiCad 5-era numbering/casing used here previously emitted
# B.Cu=31 and ECO1.User/ECO2.User, which triggers "not fixed layer hash" load
# failures for placement preview boards. Keep this table aligned with a board
# freshly written by KiCad 10.
_LAYERS = """\
  (layers
    (0 "F.Cu" signal)
    (2 "B.Cu" signal)
    (9 "F.Adhes" user "F.Adhesive")
    (11 "B.Adhes" user "B.Adhesive")
    (13 "F.Paste" user)
    (15 "B.Paste" user)
    (5 "F.SilkS" user "F.Silkscreen")
    (7 "B.SilkS" user "B.Silkscreen")
    (1 "F.Mask" user)
    (3 "B.Mask" user)
    (17 "Dwgs.User" user "User.Drawings")
    (19 "Cmts.User" user "User.Comments")
    (21 "Eco1.User" user "User.Eco1")
    (23 "Eco2.User" user "User.Eco2")
    (25 "Edge.Cuts" user)
    (27 "Margin" user)
    (31 "F.CrtYd" user "F.Courtyard")
    (29 "B.CrtYd" user "B.Courtyard")
    (35 "F.Fab" user)
    (33 "B.Fab" user)
    (39 "User.1" user)
    (41 "User.2" user)
    (43 "User.3" user)
    (45 "User.4" user)
  )"""

_SETUP = """\
  (setup
    (pad_to_mask_clearance 0.05)
    (allow_soldermask_bridges_in_footprints no)
    (pcbplotparams
      (layerselection 0x00010fc_ffffffff)
      (plot_on_all_layers_selection 0x0000000_00000000)
      (disableapertmacros no)
      (usegerberextensions no)
      (usegerberattributes yes)
      (usegerberadvancedattributes yes)
      (creategerberjobfile yes)
      (dashed_line_dash_ratio 12.000000)
      (dashed_line_gap_ratio 3.000000)
      (svgprecision 4)
      (plotframeref no)
      (viasonmask no)
      (mode 1)
      (useauxorigin no)
      (hpglpennumber 1)
      (hpglpenspeed 20)
      (hpglpendiameter 15.000000)
      (pdf_front_fp_property_popups yes)
      (pdf_back_fp_property_popups yes)
      (dxfpolygonmode yes)
      (dxfimperialunits yes)
      (dxfusepcbnewfont yes)
      (psnegative no)
      (psa4output no)
      (plotreference yes)
      (plotvalue yes)
      (plotfptext yes)
      (plotinvisibletext no)
      (sketchpadsonfab no)
      (subtractmaskfromsilk no)
      (outputformat 1)
      (mirror no)
      (drillshape 1)
      (scaleselection 1)
      (outputdirectory "")
    )
  )"""


# ---- Zone placement by category ----
# Each zone is a rectangular region on the board.
# Categories map to zones; items within a zone are laid out in rows.
_ZONE_MAP = {
    "power": "power",
    "regulator": "power",
    "poe": "power",
    "digital": "digital",
    "mcu": "digital",
    "fpga": "digital",
    "rf": "rf",
    "transceiver": "rf",
    "clock": "digital",
    "connector": "connector",
    "sensor": "sensor",
    "storage": "digital",
    "debug": "connector",
    "communication": "digital",
    "ethernet": "digital",
    "usb": "connector",
    "protection": "rf",
    "passive": "passive",
}


def _classify_net(net_name: str) -> str:
    """Return the net class name for a given net name."""
    upper = net_name.upper()
    if upper == "GND" or upper.startswith("GND_"):
        return "Power_1A"
    if upper.startswith(("VDD", "VCC", "VBUS")):
        # High-current power rails (input power, bus power)
        if any(tag in upper for tag in ("VBUS", "VIN", "5V", "12V")):
            return "Power_3A"
        return "Power_1A"
    return "Default"


def _footprint_size_mm(comp: ComponentDef) -> tuple[float, float]:
    """Estimate footprint bounding-box size in mm from the footprint string."""
    fp = comp.footprint.lower() if comp.footprint else ""

    # SMD passives: extract from metric code
    m = re.search(r"(\d{4})metric", fp)
    if m:
        code = m.group(1)
        # Metric codes: 0402=0.4x0.2, 0603=0.6x0.3, etc. (in 0.1mm)
        w = int(code[:2]) / 10.0 + 1.0  # add pad margin
        h = int(code[2:]) / 10.0 + 1.0
        return max(w, 2.0), max(h, 2.0)

    # QFP/QFN: extract body size
    m = re.search(r"(\d+)x(\d+)", fp)
    if m:
        return float(m.group(1)) + 2.0, float(m.group(2)) + 2.0

    # BGA: estimate from pin count
    pin_count = len(comp.pins)
    if pin_count > 200:
        return 25.0, 25.0
    if pin_count > 80:
        return 18.0, 18.0
    if pin_count > 40:
        return 12.0, 12.0
    if pin_count > 10:
        return 8.0, 8.0
    return 5.0, 5.0


def _build_net_list(components: list[ComponentDef]) -> list[str]:
    """Collect all unique net names from components, sorted."""
    nets = set()
    for comp in components:
        nets.update(comp.pin_nets.values())
        nets.update(comp.power_pins.values())
        for bc in comp.bypass_caps:
            nets.add(bc.net)
            nets.add(bc.gnd_net)
        for sr in comp.straps:
            nets.add(sr.net)
            nets.add(sr.rail)
    nets.discard("")
    return sorted(nets)


def _build_net_classes(nets: list[str]) -> dict[str, list[str]]:
    """Group nets by net class."""
    classes = {"Default": [], "Power_1A": [], "Power_3A": []}
    for net in nets:
        cls = _classify_net(net)
        classes[cls].append(net)
    return classes


def _footprint_sexpr(
    ref: str,
    value: str,
    footprint: str,
    x: float,
    y: float,
) -> str:
    """Generate a minimal footprint S-expression for placement hint.

    Sprint 40 Task 171 — this file is a **placement preview**, not a
    fabrication-ready PCB. It carries reference locations and board outline
    so the user can review layout before running the KiCad schematic →
    PCB flow. Previously we fell back to ``SOIC-8_3.9x4.9mm_P1.27mm``
    when a component had no footprint, and we synthesized two 1.27-pitch
    SMD pads for every footprint regardless of its real pad count — which
    produced physically misleading geometry (e.g. an ESP32-S3-WROOM-1
    module with only two pads).

    Current policy:
    * When ``footprint`` is provided, emit the real footprint reference and
      no pads. KiCad's forward-annotation from the schematic is the
      authoritative source of pads; this file is only a layout hint.
    * When ``footprint`` is missing, emit a clearly-labelled placeholder
      (``Placement_Preview:Missing_<ref>``) and still no pads. The file
      itself ships with a header comment calling out preview status.

    Zero pads are emitted — KiCad's forward-annotation is authoritative.
    """
    if footprint:
        fp_lib = footprint
    else:
        fp_lib = f"Placement_Preview:Missing_{ref}"
    lines = [
        f'  (footprint "{fp_lib}"',
        '    (layer "F.Cu")',
        f"    (at {x:.2f} {y:.2f})",
        f'    (property "Reference" "{ref}" (at 0 -2 0)',
        "      (effects (font (size 1.0 1.0) (thickness 0.15)))",
        "    )",
        f'    (property "Value" "{value}" (at 0 2 0)',
        "      (effects (font (size 1.0 1.0) (thickness 0.15)))",
        "    )",
    ]
    lines.append("  )")
    return "\n".join(lines)


def _edge_cuts_rect(x1: float, y1: float, x2: float, y2: float) -> str:
    """Generate board outline as four gr_line segments on Edge.Cuts layer."""
    corners = [(x1, y1), (x2, y1), (x2, y2), (x1, y2)]
    lines = []
    for i in range(4):
        sx, sy = corners[i]
        ex, ey = corners[(i + 1) % 4]
        lines.append(
            f"  (gr_line (start {sx:.2f} {sy:.2f}) (end {ex:.2f} {ey:.2f})"
            f' (stroke (width 0.1) (type solid)) (layer "Edge.Cuts"))'
        )
    return "\n".join(lines)


def generate_pcb_placement(
    components: list[ComponentDef],
    output_path: str | Path,
    project_name: str = "project",
) -> tuple[str, dict[str, tuple[float, float, float, str]]]:
    """Generate a .kicad_pcb placement hint file.

    Args:
        components: list of ComponentDef instances (same as passed to generate_from_components)
        output_path: directory to write the PCB file into
        project_name: used for the filename ({project_name}_placement.kicad_pcb)

    Returns:
        Tuple of (path_to_pcb_file, placements_dict) where:
        - path_to_pcb_file: str, path to the generated PCB file
        - placements_dict: {ref: (x_mm, y_mm, rotation_deg, layer_str)} for CPL/BOM export
    """
    output_path = Path(output_path)
    output_path.mkdir(parents=True, exist_ok=True)

    # Collect nets and assign net numbers
    net_names = _build_net_list(components)
    net_map = {name: idx + 1 for idx, name in enumerate(net_names)}  # net 0 = ""
    net_classes = _build_net_classes(net_names)

    # Group components by zone
    zones: dict[str, list[ComponentDef]] = {
        "power": [],
        "digital": [],
        "rf": [],
        "connector": [],
        "sensor": [],
        "passive": [],
    }
    ref_counter: dict[str, int] = {}
    reserved_refs: set[str] = set()
    placed_refs: set[str] = set()

    def _reserve_ref(ref: str) -> None:
        if not ref:
            return
        reserved_refs.add(ref)
        match = re.match(r"^([A-Za-z]+)(\d+)$", ref)
        if not match:
            return
        prefix, number = match.groups()
        ref_counter[prefix.upper()] = max(ref_counter.get(prefix.upper(), 0), int(number))

    def _next_ref(prefix: str) -> str:
        prefix = (prefix or "U").upper()
        if prefix not in ref_counter:
            ref_counter[prefix] = 0
        while True:
            ref_counter[prefix] += 1
            ref = f"{prefix}{ref_counter[prefix]}"
            if ref not in reserved_refs and ref not in placed_refs:
                placed_refs.add(ref)
                return ref

    for comp in components:
        zone = _ZONE_MAP.get(comp.category, "digital")
        if zone not in zones:
            zone = "digital"
        zones[zone].append(comp)
        if comp.source_ref:
            _reserve_ref(comp.source_ref)

    # Zone layout regions (x_start, y_start) in mm — relative positions on the board
    # Power: top-left, Digital: center, RF: top-right,
    # Connectors: left/bottom edge, Sensors: bottom-right, Passives: near center-bottom
    zone_origins = {
        "power": (10.0, 10.0),
        "digital": (50.0, 30.0),
        "rf": (90.0, 10.0),
        "connector": (10.0, 60.0),
        "sensor": (90.0, 60.0),
        "passive": (50.0, 70.0),
    }

    # Place footprints within each zone
    footprints = []
    placements: dict[str, tuple[float, float, float, str]] = {}  # ref -> (x, y, rotation, layer)
    max_x = 0.0
    max_y = 0.0

    for zone_name, zone_comps in zones.items():
        if not zone_comps:
            continue
        ox, oy = zone_origins[zone_name]
        cx, cy = ox, oy
        row_height = 0.0
        zone_width = 60.0  # max width before wrapping

        for comp in zone_comps:
            fw, fh = _footprint_size_mm(comp)

            # Wrap to next row if exceeding zone width
            if cx - ox + fw > zone_width:
                cx = ox
                cy += row_height + 3.0
                row_height = 0.0

            # Preserve schematic/BOM refs when present so the placement hint
            # stays traceable back to the generated schematic.
            explicit_ref = comp.source_ref or ""
            if explicit_ref and explicit_ref not in placed_refs:
                ref = explicit_ref
                placed_refs.add(ref)
            else:
                ref = _next_ref(comp.ref_prefix or "U")

            footprints.append(_footprint_sexpr(ref, comp.value, comp.footprint, cx, cy))
            placements[ref] = (cx, cy, 0.0, "top")  # x, y in mm, rotation 0°, layer F.Cu

            max_x = max(max_x, cx + fw)
            max_y = max(max_y, cy + fh)
            cx += fw + 3.0
            row_height = max(row_height, fh)

    # Board outline with 5mm margin
    margin = 5.0
    board_x1 = 0.0
    board_y1 = 0.0
    board_x2 = max(max_x + margin, 50.0)  # minimum 50mm
    board_y2 = max(max_y + margin, 40.0)  # minimum 40mm

    # Build the PCB file. The generator name is intentional — "schematic_engine
    # placement_preview" tells reviewers this is a layout hint, not a
    # fabrication-ready board. Real footprints and routing come from
    # forward-annotating the generated schematic through KiCad. Footprints
    # whose lib_id is ``Placement_Preview:Missing_*`` lacked a binding when
    # the spec was generated — resolve those in YAML before fab.
    parts = []
    parts.append('(kicad_pcb (version 20240108) (generator "schematic_engine placement_preview")')
    parts.append("  (general (thickness 1.6) (legacy_teardrops no))")
    parts.append(_LAYERS)
    parts.append(_SETUP)

    # Net declarations
    parts.append('  (net 0 "")')
    for name, idx in sorted(net_map.items(), key=lambda kv: kv[1]):
        parts.append(f'  (net {idx} "{name}")')

    # Net classes with per-net membership
    default_nets = net_classes.get("Default", [])
    power1a_nets = net_classes.get("Power_1A", [])
    power3a_nets = net_classes.get("Power_3A", [])

    parts.append('  (net_class "Default" "Default net class"')
    parts.append("    (clearance 0.2) (trace_width 0.2) (via_dia 0.6) (via_drill 0.3)")
    parts.append("    (uvia_dia 0.3) (uvia_drill 0.1)")
    for net in default_nets:
        parts.append(f'    (add_net "{net}")')
    parts.append("  )")
    parts.append('  (net_class "Power_1A" "Power nets (1A)"')
    parts.append("    (clearance 0.2) (trace_width 0.5) (via_dia 0.8) (via_drill 0.4)")
    parts.append("    (uvia_dia 0.3) (uvia_drill 0.1)")
    for net in power1a_nets:
        parts.append(f'    (add_net "{net}")')
    parts.append("  )")
    parts.append('  (net_class "Power_3A" "High-current power nets (3A)"')
    parts.append("    (clearance 0.25) (trace_width 1.0) (via_dia 1.0) (via_drill 0.5)")
    parts.append("    (uvia_dia 0.3) (uvia_drill 0.1)")
    for net in power3a_nets:
        parts.append(f'    (add_net "{net}")')
    parts.append("  )")

    # Footprints
    for fp in footprints:
        parts.append(fp)

    # Board outline
    parts.append(_edge_cuts_rect(board_x1, board_y1, board_x2, board_y2))

    parts.append(")")

    pcb_file = output_path / f"{project_name}_placement.kicad_pcb"
    pcb_file.write_text("\n".join(parts), encoding="utf-8")

    _logger.info("PCB placement hint: %s", pcb_file)
    _logger.info(
        "Board: %.1f x %.1f mm, %d footprints, %d nets, %d net-class assignments",
        board_x2, board_y2, len(footprints), len(net_names),
        sum(len(v) for v in net_classes.values()),
    )

    return str(pcb_file), placements
