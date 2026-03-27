#!/usr/bin/env python3
"""
KiCad PCB Layout Analyzer — comprehensive single-pass extraction.

Parses a .kicad_pcb file and outputs structured JSON with:
- Board dimensions and layer stack
- Footprint inventory (components, positions, pads, nets)
- Routing analysis (tracks, vias, zones)
- Net connectivity and unrouted nets
- Design rule summary
- Statistics

Usage:
    python analyze_pcb.py <file.kicad_pcb> [--output file.json]
"""

import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import re

from sexp_parser import (
    find_all,
    find_first,
    get_at,
    get_property,
    get_value,
    parse_file,
)


# ---------------------------------------------------------------------------
# Geometry helpers
# ---------------------------------------------------------------------------

def _shoelace_area(pts_node: list) -> float:
    """Compute polygon area from a (pts (xy x y) ...) node using shoelace formula.

    Returns positive area in mm². Operates directly on parsed S-expression
    nodes to avoid allocating an intermediate coordinate list.
    """
    xys = find_all(pts_node, "xy")
    n = len(xys)
    if n < 3:
        return 0.0
    area = 0.0
    for i in range(n):
        j = (i + 1) % n
        x_i, y_i = float(xys[i][1]), float(xys[i][2])
        x_j, y_j = float(xys[j][1]), float(xys[j][2])
        area += x_i * y_j - x_j * y_i
    return abs(area) / 2.0


def _extract_polygon_coords(pts_node: list) -> list[tuple[float, float]]:
    """Extract (x, y) coordinate tuples from a (pts (xy x y) ...) node."""
    return [(float(xy[1]), float(xy[2])) for xy in find_all(pts_node, "xy")]


def _shoelace_area_from_coords(coords: list[tuple[float, float]]) -> float:
    """Compute polygon area from coordinate list using shoelace formula."""
    n = len(coords)
    if n < 3:
        return 0.0
    area = 0.0
    for i in range(n):
        j = (i + 1) % n
        area += coords[i][0] * coords[j][1] - coords[j][0] * coords[i][1]
    return abs(area) / 2.0


def _point_in_polygon(px: float, py: float,
                      polygon: list[tuple[float, float]]) -> bool:
    """Ray-casting point-in-polygon test.

    Returns True if point (px, py) is inside the polygon defined by
    a list of (x, y) vertices.
    """
    n = len(polygon)
    if n < 3:
        return False
    inside = False
    j = n - 1
    for i in range(n):
        xi, yi = polygon[i]
        xj, yj = polygon[j]
        if ((yi > py) != (yj > py)) and \
                (px < (xj - xi) * (py - yi) / (yj - yi) + xi):
            inside = not inside
        j = i
    return inside


def _polygon_bbox(
    coords: list[tuple[float, float]],
) -> tuple[float, float, float, float]:
    """Compute bounding box of a polygon.

    Returns (min_x, min_y, max_x, max_y).
    """
    xs = [p[0] for p in coords]
    ys = [p[1] for p in coords]
    return (min(xs), min(ys), max(xs), max(ys))


class ZoneFills:
    """Spatial index for zone filled polygon data.

    Stores filled polygon coordinates extracted during zone parsing.
    Used for point-in-polygon queries to determine actual copper presence
    at specific locations. Not included in JSON output (coordinates are
    too large — often thousands of vertices per fill region).

    Requires that zones have been filled in KiCad (Edit → Fill All Zones)
    before the PCB file was saved. Stale fills will produce incorrect results.
    """

    def __init__(self) -> None:
        self._fills: list[
            tuple[int, str, list[tuple[float, float]],
                  tuple[float, float, float, float]]
        ] = []

    def add(self, zone_idx: int, layer: str,
            coords: list[tuple[float, float]]) -> None:
        """Register a filled polygon region for spatial queries."""
        bbox = _polygon_bbox(coords)
        self._fills.append((zone_idx, layer, coords, bbox))

    @property
    def has_data(self) -> bool:
        """True if any filled polygon data was loaded."""
        return len(self._fills) > 0

    def zones_at_point(self, x: float, y: float, layer: str,
                       zones: list[dict]) -> list[dict]:
        """Return zone dicts that have filled copper at (x, y) on layer."""
        results = []
        seen: set[int] = set()
        for zone_idx, fill_layer, coords, bbox in self._fills:
            if fill_layer != layer or zone_idx in seen:
                continue
            # Fast bounding box rejection
            if x < bbox[0] or x > bbox[2] or y < bbox[1] or y > bbox[3]:
                continue
            if _point_in_polygon(x, y, coords):
                results.append(zones[zone_idx])
                seen.add(zone_idx)
        return results

    def has_copper_at(self, x: float, y: float, layer: str) -> bool:
        """Check if any zone has filled copper at (x, y) on layer."""
        for _zone_idx, fill_layer, coords, bbox in self._fills:
            if fill_layer != layer:
                continue
            if x < bbox[0] or x > bbox[2] or y < bbox[1] or y > bbox[3]:
                continue
            if _point_in_polygon(x, y, coords):
                return True
        return False

    def zone_nets_at_point(self, x: float, y: float, layer: str,
                           zones: list[dict]) -> list[str]:
        """Return net names of zones with filled copper at (x, y) on layer."""
        return [z["net_name"] for z in self.zones_at_point(x, y, layer, zones)
                if z.get("net_name")]


def _arc_length_3pt(sx: float, sy: float, mx: float, my: float,
                    ex: float, ey: float) -> float:
    """Compute arc length from three points (start, mid, end) on a circle."""
    D = 2.0 * (sx * (my - ey) + mx * (ey - sy) + ex * (sy - my))
    if abs(D) < 1e-10:
        # Collinear — treat as straight line
        return math.sqrt((ex - sx) ** 2 + (ey - sy) ** 2)

    ss = sx * sx + sy * sy
    ms = mx * mx + my * my
    es = ex * ex + ey * ey
    ux = (ss * (my - ey) + ms * (ey - sy) + es * (sy - my)) / D
    uy = (ss * (ex - mx) + ms * (sx - ex) + es * (mx - sx)) / D
    R = math.sqrt((sx - ux) ** 2 + (sy - uy) ** 2)

    a_s = math.atan2(sy - uy, sx - ux)
    a_m = math.atan2(my - uy, mx - ux)
    a_e = math.atan2(ey - uy, ex - ux)

    # Normalize angles relative to start
    def _norm(a: float) -> float:
        a = (a - a_s) % (2.0 * math.pi)
        return a

    nm = _norm(a_m)
    ne = _norm(a_e)

    # Arc from start to end: two possible arcs (CCW ne, or CW 2π-ne).
    # Choose the one containing mid.
    if ne > 0 and 0 < nm < ne:
        arc_angle = ne
    elif ne > 0:
        arc_angle = 2.0 * math.pi - ne
    else:
        arc_angle = 2.0 * math.pi  # full circle edge case
    return R * arc_angle


def extract_layers(root: list) -> list[dict]:
    """Extract layer definitions."""
    layers_node = find_first(root, "layers")
    if not layers_node:
        return []

    layers = []
    for item in layers_node[1:]:
        if isinstance(item, list) and len(item) >= 3:
            layers.append({
                "number": int(item[0]) if str(item[0]).isdigit() else item[0],
                "name": item[1],
                "type": item[2],
                "alias": item[3] if len(item) > 3 else None,
            })
    return layers


def extract_setup(root: list) -> dict:
    """Extract board setup, stackup, and design rules."""
    setup_node = find_first(root, "setup")
    if not setup_node:
        return {}

    result = {}

    # Board thickness
    general = find_first(root, "general")
    if general:
        thickness = get_value(general, "thickness")
        if thickness:
            result["board_thickness_mm"] = float(thickness)

    # Stackup
    stackup = find_first(setup_node, "stackup")
    if stackup:
        stack_layers = []
        for layer in find_all(stackup, "layer"):
            layer_info = {"name": layer[1] if len(layer) > 1 else ""}
            for item in layer[2:]:
                if isinstance(item, list) and len(item) >= 2:
                    layer_info[item[0]] = item[1]
            stack_layers.append(layer_info)
        result["stackup"] = stack_layers

    # Design rules from setup
    _float_keys = [
        "pad_to_mask_clearance", "solder_mask_min_width",
        "pad_to_paste_clearance",
    ]
    for key in _float_keys:
        val = get_value(setup_node, key)
        if val:
            result[key] = float(val)

    # Paste clearance ratio
    pcr = get_value(setup_node, "pad_to_paste_clearance_ratio")
    if pcr:
        result["pad_to_paste_clearance_ratio"] = float(pcr)

    # Copper finish from stackup
    if stackup:
        cf = get_value(stackup, "copper_finish")
        if cf:
            result["copper_finish"] = cf
        dc = get_value(stackup, "dielectric_constraints")
        if dc:
            result["dielectric_constraints"] = dc

    # Legacy teardrops flag
    if general:
        lt = get_value(general, "legacy_teardrops")
        if lt:
            result["legacy_teardrops"] = lt

    # Soldermask bridges
    smb = get_value(setup_node, "allow_soldermask_bridges_in_footprints")
    if smb:
        result["allow_soldermask_bridges"] = smb

    # Design rules from pcbplotparams or design_settings (varies by version)
    # KiCad 9 stores rules in the .kicad_pro file, but some appear in the PCB
    # under (setup (design_settings ...)) or directly
    ds = find_first(setup_node, "design_settings") or setup_node
    for key in ["min_clearance", "min_track_width", "min_via_diameter",
                "min_via_drill", "min_uvia_diameter", "min_uvia_drill",
                "min_through_hole_pad", "min_hole_clearance"]:
        val = get_value(ds, key)
        if val:
            result.setdefault("design_rules", {})[key] = float(val)

    return result


def extract_nets(root: list) -> dict[int, str]:
    """Extract net declarations."""
    nets = {}
    for item in root:
        if isinstance(item, list) and len(item) >= 3 and item[0] == "net":
            net_num = int(item[1])
            net_name = item[2]
            nets[net_num] = net_name
    return nets


def extract_footprints(root: list) -> list[dict]:
    """Extract all placed footprints with pad details.

    Handles both KiCad 6+ (footprint ...) and KiCad 5 (module ...) formats.
    """
    footprints = []

    # KiCad 6+: (footprint ...), KiCad 5: (module ...)
    fp_nodes = find_all(root, "footprint") or find_all(root, "module")

    for fp in fp_nodes:
        fp_lib = fp[1] if len(fp) > 1 else ""
        at = get_at(fp)
        x, y, angle = at if at else (0, 0, 0)

        layer = get_value(fp, "layer") or "F.Cu"

        # KiCad 6+: (property "Reference" "R1"), KiCad 5: (fp_text reference "R1")
        ref = get_property(fp, "Reference") or ""
        value = get_property(fp, "Value") or ""
        if not ref:
            for ft in find_all(fp, "fp_text"):
                if len(ft) >= 3:
                    if ft[1] == "reference":
                        ref = ft[2]
                    elif ft[1] == "value":
                        value = ft[2]

        mpn = get_property(fp, "MPN") or get_property(fp, "Mfg Part") or ""

        # Determine SMD vs through-hole + extended attributes
        attr_node = find_first(fp, "attr")
        attr_flags: list[str] = []
        if attr_node and len(attr_node) > 1:
            attr_flags = [a for a in attr_node[1:] if isinstance(a, str)]
            attr = attr_flags[0] if attr_flags else "smd"
        else:
            # Infer from pad types if attr not present (KiCad 5)
            has_tht = any(p[2] == "thru_hole" for p in find_all(fp, "pad") if len(p) > 2)
            attr = "through_hole" if has_tht else "smd"
            # KiCad 5 uses "virtual" for board-only items
            if attr_node and len(attr_node) > 1 and attr_node[1] == "virtual":
                attr = "smd"
                attr_flags = ["virtual"]

        is_dnp = "dnp" in attr_flags
        is_board_only = "board_only" in attr_flags or "virtual" in attr_flags
        exclude_from_bom = "exclude_from_bom" in attr_flags or is_board_only
        exclude_from_pos = "exclude_from_pos_files" in attr_flags or is_board_only

        # Schematic cross-reference (KiCad 6+)
        sch_path = get_value(fp, "path") or ""
        sch_sheetname = get_value(fp, "sheetname") or ""
        sch_sheetfile = get_value(fp, "sheetfile") or ""

        # Net tie pad groups
        net_tie_node = find_first(fp, "net_tie_pad_groups")
        net_tie_groups = None
        if net_tie_node and len(net_tie_node) > 1:
            net_tie_groups = net_tie_node[1]

        # Extended properties (MPN, manufacturer, etc.)
        manufacturer = get_property(fp, "Manufacturer") or ""
        digikey_pn = get_property(fp, "DigiKey Part") or ""
        description = get_property(fp, "Description") or ""

        # 3D model references
        models = []
        for model in find_all(fp, "model"):
            if len(model) > 1:
                models.append(model[1])

        # Extract pads
        pads = []
        for pad in find_all(fp, "pad"):
            if len(pad) < 4:
                continue
            pad_num = pad[1]
            pad_type = pad[2]  # smd, thru_hole, np_thru_hole
            pad_shape = pad[3]  # circle, rect, oval, roundrect, custom

            pad_at = get_at(pad)
            pad_size = find_first(pad, "size")
            pad_drill = find_first(pad, "drill")
            pad_net = find_first(pad, "net")
            pad_layers = find_first(pad, "layers")

            pad_info = {
                "number": pad_num,
                "type": pad_type,
                "shape": pad_shape,
            }

            if pad_at:
                # Pad position is relative to footprint; compute absolute
                px, py = pad_at[0], pad_at[1]
                pad_angle = pad_at[2]
                # Rotate pad position by footprint angle
                if angle != 0:
                    rad = math.radians(angle)
                    rpx = px * math.cos(rad) - py * math.sin(rad)
                    rpy = px * math.sin(rad) + py * math.cos(rad)
                    px, py = rpx, rpy
                pad_info["abs_x"] = round(x + px, 4)
                pad_info["abs_y"] = round(y + py, 4)
                if pad_angle != 0:
                    pad_info["angle"] = pad_angle

            if pad_size and len(pad_size) >= 3:
                pad_info["width"] = float(pad_size[1])
                pad_info["height"] = float(pad_size[2])

            if pad_drill and len(pad_drill) >= 2:
                # Drill can be (drill D) or (drill oval W H) or (drill D (offset X Y))
                drill_val = pad_drill[1]
                if drill_val == "oval" and len(pad_drill) >= 4:
                    pad_info["drill"] = float(pad_drill[2])  # use width
                    pad_info["drill_h"] = float(pad_drill[3])
                    pad_info["drill_shape"] = "oval"
                else:
                    try:
                        pad_info["drill"] = float(drill_val)
                    except (ValueError, TypeError):
                        pass  # skip malformed drill entries

            if pad_net and len(pad_net) >= 3:
                pad_info["net_number"] = int(pad_net[1])
                pad_info["net_name"] = pad_net[2]

            if pad_layers and len(pad_layers) > 1:
                pad_info["layers"] = [l for l in pad_layers[1:] if isinstance(l, str)]

            # Pin function and type (from schematic, carried into PCB)
            pinfunc = get_value(pad, "pinfunction")
            pintype = get_value(pad, "pintype")
            if pinfunc:
                pad_info["pinfunction"] = pinfunc
            if pintype:
                pad_info["pintype"] = pintype

            # Per-pad zone connection override
            zc = get_value(pad, "zone_connect")
            if zc is not None:
                pad_info["zone_connect"] = int(zc)

            # Custom pad shape — flag it and estimate copper area from primitives
            if pad_shape == "custom":
                pad_info["is_custom"] = True
                primitives = find_first(pad, "primitives")
                if primitives:
                    custom_area = 0.0
                    for prim in find_all(primitives, "gr_poly"):
                        pts = find_first(prim, "pts")
                        if pts:
                            custom_area += _shoelace_area(pts)
                    if custom_area > 0:
                        pad_info["custom_copper_area_mm2"] = round(custom_area, 3)

            # Pad-level solder mask/paste overrides
            sm_margin = get_value(pad, "solder_mask_margin")
            sp_margin = get_value(pad, "solder_paste_margin")
            sp_ratio = get_value(pad, "solder_paste_margin_ratio")
            if sm_margin:
                pad_info["solder_mask_margin"] = float(sm_margin)
            if sp_margin:
                pad_info["solder_paste_margin"] = float(sp_margin)
            if sp_ratio:
                pad_info["solder_paste_ratio"] = float(sp_ratio)

            pads.append(pad_info)

        # Extract courtyard bounding box (absolute coordinates)
        crtyd_pts: list[tuple[float, float]] = []
        for gtype in ("fp_line", "fp_rect", "fp_circle"):
            for item in find_all(fp, gtype):
                item_layer = get_value(item, "layer")
                if not item_layer or "CrtYd" not in item_layer:
                    continue
                for key in ("start", "end", "center"):
                    node = find_first(item, key)
                    if node and len(node) >= 3:
                        lx, ly = float(node[1]), float(node[2])
                        # Transform to absolute coordinates
                        if angle != 0:
                            rad = math.radians(angle)
                            rx = lx * math.cos(rad) - ly * math.sin(rad)
                            ry = lx * math.sin(rad) + ly * math.cos(rad)
                            lx, ly = rx, ry
                        crtyd_pts.append((x + lx, y + ly))

        fp_entry: dict = {
            "library": fp_lib,
            "reference": ref,
            "value": value,
            "mpn": mpn,
            "x": x,
            "y": y,
            "angle": angle,
            "layer": layer,
            "type": attr,
            "pad_count": len(pads),
            "pads": pads,
        }

        # Extended attributes
        if is_dnp:
            fp_entry["dnp"] = True
        if is_board_only:
            fp_entry["board_only"] = True
        if exclude_from_bom:
            fp_entry["exclude_from_bom"] = True
        if exclude_from_pos:
            fp_entry["exclude_from_pos"] = True

        # Schematic cross-reference
        if sch_path:
            fp_entry["sch_path"] = sch_path
        if sch_sheetname:
            fp_entry["sheetname"] = sch_sheetname
        if sch_sheetfile:
            fp_entry["sheetfile"] = sch_sheetfile

        # Net tie
        if net_tie_groups:
            fp_entry["net_tie_pad_groups"] = net_tie_groups

        # Extended properties
        if manufacturer:
            fp_entry["manufacturer"] = manufacturer
        if digikey_pn:
            fp_entry["digikey_pn"] = digikey_pn
        if description:
            fp_entry["description"] = description

        # 3D models
        if models:
            fp_entry["models_3d"] = models

        if crtyd_pts:
            cxs = [p[0] for p in crtyd_pts]
            cys = [p[1] for p in crtyd_pts]
            fp_entry["courtyard"] = {
                "min_x": round(min(cxs), 3), "min_y": round(min(cys), 3),
                "max_x": round(max(cxs), 3), "max_y": round(max(cys), 3),
            }

        footprints.append(fp_entry)

    return footprints


def extract_tracks(root: list) -> dict:
    """Extract track segments with statistics."""
    segments = []
    for seg in find_all(root, "segment"):
        start = find_first(seg, "start")
        end = find_first(seg, "end")
        width = get_value(seg, "width")
        layer = get_value(seg, "layer")
        net = get_value(seg, "net")

        if start and end:
            segments.append({
                "x1": float(start[1]), "y1": float(start[2]),
                "x2": float(end[1]), "y2": float(end[2]),
                "width": float(width) if width else 0,
                "layer": layer or "",
                "net": int(net) if net else 0,
            })

    # Also extract arcs
    arcs = []
    for arc in find_all(root, "arc"):
        start = find_first(arc, "start")
        mid = find_first(arc, "mid")
        end = find_first(arc, "end")
        width = get_value(arc, "width")
        layer = get_value(arc, "layer")
        net = get_value(arc, "net")

        if start and end:
            arcs.append({
                "start": [float(start[1]), float(start[2])],
                "mid": [float(mid[1]), float(mid[2])] if mid else None,
                "end": [float(end[1]), float(end[2])],
                "width": float(width) if width else 0,
                "layer": layer or "",
                "net": int(net) if net else 0,
            })

    # Width statistics
    widths = {}
    for seg in segments:
        w = seg["width"]
        widths[w] = widths.get(w, 0) + 1
    for arc in arcs:
        w = arc["width"]
        widths[w] = widths.get(w, 0) + 1

    # Layer distribution
    layer_dist = {}
    for seg in segments:
        l = seg["layer"]
        layer_dist[l] = layer_dist.get(l, 0) + 1
    for arc in arcs:
        l = arc["layer"]
        layer_dist[l] = layer_dist.get(l, 0) + 1

    return {
        "segment_count": len(segments),
        "arc_count": len(arcs),
        "total_count": len(segments) + len(arcs),
        "width_distribution": widths,
        "layer_distribution": layer_dist,
        "segments": segments,
        "arcs": arcs,
    }


def extract_vias(root: list) -> dict:
    """Extract vias with statistics."""
    vias = []
    for via in find_all(root, "via"):
        at = get_at(via)
        size = get_value(via, "size")
        drill = get_value(via, "drill")
        net = get_value(via, "net")
        layers_node = find_first(via, "layers")
        via_type = get_value(via, "type")  # blind, micro, etc.

        via_info = {
            "x": at[0] if at else 0,
            "y": at[1] if at else 0,
            "size": float(size) if size else 0,
            "drill": float(drill) if drill else 0,
            "net": int(net) if net else 0,
        }
        if layers_node and len(layers_node) > 1:
            via_info["layers"] = [l for l in layers_node[1:] if isinstance(l, str)]
        if via_type:
            via_info["type"] = via_type
        # Free (unanchored) vias — typically stitching or thermal
        if get_value(via, "free") == "yes":
            via_info["free"] = True
        # Via tenting
        tenting = find_first(via, "tenting")
        if tenting and len(tenting) > 1:
            via_info["tenting"] = [t for t in tenting[1:] if isinstance(t, str)]

        vias.append(via_info)

    # Size distribution
    sizes = {}
    for v in vias:
        key = f"{v['size']}/{v['drill']}"
        sizes[key] = sizes.get(key, 0) + 1

    return {
        "count": len(vias),
        "size_distribution": sizes,
        "vias": vias,
    }


def extract_zones(root: list) -> tuple[list[dict], ZoneFills]:
    """Extract copper zones with outline and filled polygon area/spatial data.

    Computes:
    - outline_area_mm2: area of the user-drawn zone boundary
    - outline_bbox: bounding box of the zone outline [min_x, min_y, max_x, max_y]
    - filled_area_mm2: total copper fill area (sum of all filled_polygon regions)
    - filled_bbox: bounding box of all filled polygons combined
    - fill_ratio: filled_area / outline_area (1.0 = fully filled, <1.0 = has gaps)
    - filled_layers: per-layer filled area breakdown
    - is_filled: whether the zone has been filled (has filled_polygon data)

    Returns:
        (zones, zone_fills) — zone_fills is a spatial index for point-in-polygon
        queries against the filled copper. The filled polygon coordinates are
        kept in memory (not in the JSON output) because they can be very large.
        Zone fills reflect the last time Fill All Zones was run in KiCad.
    """
    zones = []
    zone_fills = ZoneFills()
    for zone_idx, zone in enumerate(find_all(root, "zone")):
        net = get_value(zone, "net")
        net_name = get_value(zone, "net_name")
        layer = get_value(zone, "layer")
        layers_node = find_first(zone, "layers")

        # Zone properties
        connect_pads = find_first(zone, "connect_pads")
        clearance = None
        pad_connection = None
        if connect_pads:
            cl = get_value(connect_pads, "clearance")
            clearance = float(cl) if cl else None
            # Connection type: first bare string after "connect_pads" keyword
            for cp_item in connect_pads[1:]:
                if isinstance(cp_item, str) and cp_item in (
                        "yes", "no", "thru_hole_only", "full", "thermal_reliefs"):
                    pad_connection = cp_item
                    break

        # Keepout zone detection
        keepout = find_first(zone, "keepout")
        keepout_restrictions = None
        if keepout:
            keepout_restrictions = {}
            for restriction in ("tracks", "vias", "pads", "copperpour", "footprints"):
                val = get_value(keepout, restriction)
                if val:
                    keepout_restrictions[restriction] = val

        # Zone priority
        priority = get_value(zone, "priority")

        # Zone name (user-assigned)
        zone_name = get_value(zone, "name")

        min_thickness = get_value(zone, "min_thickness")
        fill = find_first(zone, "fill")
        thermal_gap = None
        thermal_bridge = None
        is_filled = False
        if fill:
            tg = get_value(fill, "thermal_gap")
            tb = get_value(fill, "thermal_bridge_width")
            thermal_gap = float(tg) if tg else None
            thermal_bridge = float(tb) if tb else None
            # "yes" in fill node means the zone has been filled
            is_filled = "yes" in fill

        # Zone outline area and bounding box
        outline_area = 0.0
        outline_point_count = 0
        outline_bbox = None
        polygon = find_first(zone, "polygon")
        if polygon:
            pts = find_first(polygon, "pts")
            if pts:
                outline_coords = _extract_polygon_coords(pts)
                outline_point_count = len(outline_coords)
                outline_area = _shoelace_area_from_coords(outline_coords)
                if outline_coords:
                    outline_bbox = _polygon_bbox(outline_coords)

        # Filled polygon areas + spatial data for point-in-polygon queries
        filled_layers: dict[str, float] = {}
        total_filled_area = 0.0
        fill_count = 0
        filled_min_x = float('inf')
        filled_min_y = float('inf')
        filled_max_x = float('-inf')
        filled_max_y = float('-inf')
        for fp_node in find_all(zone, "filled_polygon"):
            fp_layer = get_value(fp_node, "layer") or layer or ""
            fp_pts = find_first(fp_node, "pts")
            if fp_pts:
                coords = _extract_polygon_coords(fp_pts)
                area = _shoelace_area_from_coords(coords)
                filled_layers[fp_layer] = filled_layers.get(fp_layer, 0.0) + area
                total_filled_area += area
                fill_count += 1
                # Store coordinates for spatial queries
                zone_fills.add(zone_idx, fp_layer, coords)
                # Track overall filled bounding box
                for cx, cy in coords:
                    if cx < filled_min_x:
                        filled_min_x = cx
                    if cy < filled_min_y:
                        filled_min_y = cy
                    if cx > filled_max_x:
                        filled_max_x = cx
                    if cy > filled_max_y:
                        filled_max_y = cy

        zone_layers = []
        if layers_node and len(layers_node) > 1:
            zone_layers = [l for l in layers_node[1:] if isinstance(l, str)]
        elif layer:
            zone_layers = [layer]

        # Compute filled bounding box (None if no fill data)
        filled_bbox = None
        if fill_count > 0 and filled_min_x != float('inf'):
            filled_bbox = (
                round(filled_min_x, 3), round(filled_min_y, 3),
                round(filled_max_x, 3), round(filled_max_y, 3),
            )

        zone_info: dict = {
            "net": int(net) if net else 0,
            "net_name": net_name or "",
            "layers": zone_layers,
            "clearance": clearance,
            "min_thickness": float(min_thickness) if min_thickness else None,
            "thermal_gap": thermal_gap,
            "thermal_bridge_width": thermal_bridge,
            "outline_points": outline_point_count,
            "outline_area_mm2": round(outline_area, 2),
            "is_filled": is_filled or fill_count > 0,
        }

        if outline_bbox:
            zone_info["outline_bbox"] = [round(v, 3) for v in outline_bbox]

        if keepout_restrictions:
            zone_info["is_keepout"] = True
            zone_info["keepout"] = keepout_restrictions
        if priority is not None:
            zone_info["priority"] = int(priority)
        if zone_name:
            zone_info["name"] = zone_name
        if pad_connection:
            zone_info["pad_connection"] = pad_connection

        if fill_count > 0:
            zone_info["filled_area_mm2"] = round(total_filled_area, 2)
            zone_info["fill_region_count"] = fill_count
            if filled_bbox:
                zone_info["filled_bbox"] = list(filled_bbox)
            if outline_area > 0:
                zone_info["fill_ratio"] = round(
                    total_filled_area / outline_area, 3)
            if len(filled_layers) > 1:
                zone_info["filled_layers"] = {
                    k: round(v, 2) for k, v in sorted(filled_layers.items())
                }

        zones.append(zone_info)

    return zones, zone_fills


def extract_board_outline(root: list) -> dict:
    """Extract board outline from Edge.Cuts layer."""
    edges = []

    for item_type in ["gr_line", "gr_arc", "gr_circle", "gr_rect"]:
        for item in find_all(root, item_type):
            layer = get_value(item, "layer")
            if layer != "Edge.Cuts":
                continue

            if item_type == "gr_line":
                start = find_first(item, "start")
                end = find_first(item, "end")
                if start and end:
                    edges.append({
                        "type": "line",
                        "start": [float(start[1]), float(start[2])],
                        "end": [float(end[1]), float(end[2])],
                    })
            elif item_type == "gr_arc":
                start = find_first(item, "start")
                mid = find_first(item, "mid")
                end = find_first(item, "end")
                if start and end:
                    edges.append({
                        "type": "arc",
                        "start": [float(start[1]), float(start[2])],
                        "mid": [float(mid[1]), float(mid[2])] if mid else None,
                        "end": [float(end[1]), float(end[2])],
                    })
            elif item_type == "gr_rect":
                start = find_first(item, "start")
                end = find_first(item, "end")
                if start and end:
                    edges.append({
                        "type": "rect",
                        "start": [float(start[1]), float(start[2])],
                        "end": [float(end[1]), float(end[2])],
                    })
            elif item_type == "gr_circle":
                center = find_first(item, "center")
                end = find_first(item, "end")
                if center and end:
                    edges.append({
                        "type": "circle",
                        "center": [float(center[1]), float(center[2])],
                        "end": [float(end[1]), float(end[2])],
                    })

    # Compute bounding box from all edge points
    all_x = []
    all_y = []
    for e in edges:
        for key in ["start", "end", "center", "mid"]:
            if key in e and e[key] is not None:
                all_x.append(e[key][0])
                all_y.append(e[key][1])

    bbox = None
    if all_x and all_y:
        bbox = {
            "min_x": min(all_x),
            "min_y": min(all_y),
            "max_x": max(all_x),
            "max_y": max(all_y),
            "width": round(max(all_x) - min(all_x), 3),
            "height": round(max(all_y) - min(all_y), 3),
        }

    return {
        "edge_count": len(edges),
        "edges": edges,
        "bounding_box": bbox,
    }


def analyze_connectivity(footprints: list[dict], tracks: dict, vias: dict,
                         net_names: dict[int, str],
                         zones: list[dict] | None = None) -> dict:
    """Analyze routing completeness — find unrouted nets.

    A net is considered routed if it has tracks, vias, or a copper zone
    covering it. Nets with only a single pad are skipped.
    """
    # Build set of nets that have pads
    pad_nets: dict[int, list[str]] = {}  # net_number -> list of "REF.pad"
    for fp in footprints:
        for pad in fp["pads"]:
            net_num = pad.get("net_number", 0)
            if net_num > 0:
                pad_nets.setdefault(net_num, []).append(f"{fp['reference']}.{pad['number']}")

    # Build set of nets that have routing (tracks, vias, or zones)
    routed_nets = set()
    for seg in tracks.get("segments", []):
        if seg["net"] > 0:
            routed_nets.add(seg["net"])
    for arc in tracks.get("arcs", []):
        if arc["net"] > 0:
            routed_nets.add(arc["net"])
    for via in vias.get("vias", []):
        if via["net"] > 0:
            routed_nets.add(via["net"])
    # Zones also route nets — a GND zone connects all GND pads
    if zones:
        for z in zones:
            zn = z.get("net", 0)
            if zn > 0:
                routed_nets.add(zn)

    # Find unrouted nets (have pads but no tracks/zones)
    unrouted = []
    for net_num, pads in pad_nets.items():
        if len(pads) >= 2 and net_num not in routed_nets:
            unrouted.append({
                "net_number": net_num,
                "net_name": net_names.get(net_num, f"net_{net_num}"),
                "pad_count": len(pads),
                "pads": pads,
            })

    return {
        "total_nets_with_pads": len(pad_nets),
        "routed_nets": len(routed_nets & set(pad_nets.keys())),
        "unrouted_count": len(unrouted),
        "routing_complete": len(unrouted) == 0,
        "unrouted": sorted(unrouted, key=lambda u: u["net_name"]),
    }


def group_components(footprints: list[dict]) -> dict:
    """Group components by reference prefix for cross-referencing with schematic."""
    groups: dict[str, list[str]] = {}
    for fp in footprints:
        ref = fp.get("reference", "")
        if not ref:
            continue
        m = re.match(r'^([A-Za-z]+)', ref)
        prefix = m.group(1) if m else ref
        groups.setdefault(prefix, []).append(ref)

    return {prefix: {"count": len(refs), "references": sorted(refs)}
            for prefix, refs in sorted(groups.items())}


def _is_power_ground_net(name: str) -> bool:
    """Check if a net name looks like power or ground."""
    if not name:
        return False
    nu = name.upper()
    if nu in ("GND", "VSS", "AGND", "DGND", "PGND", "GNDPWR", "GNDA", "GNDD",
              "VCC", "VDD", "AVCC", "AVDD", "DVCC", "DVDD", "VBUS",
              "VMAIN", "VPWR", "VSYS", "VBAT", "VCORE"):
        return True
    if nu.startswith("+") or nu.startswith("V+"):
        return True
    if nu.startswith("GND") or nu.endswith("GND"):
        return True
    if nu.startswith("VSS"):
        return True
    if len(nu) >= 3 and nu[0] == "V" and nu[1].isdigit():
        return True
    return False


def analyze_power_nets(footprints: list[dict], tracks: dict,
                       net_names: dict[int, str]) -> list[dict]:
    """Analyze routing of power/ground nets — track widths, via counts."""
    # Identify power/ground nets
    power_nets = {}
    for net_num, name in net_names.items():
        if _is_power_ground_net(name):
            power_nets[net_num] = {"name": name, "widths": set(), "track_count": 0,
                                   "total_length_mm": 0.0}

    if not power_nets:
        return []

    for seg in tracks.get("segments", []):
        net = seg["net"]
        if net in power_nets:
            power_nets[net]["widths"].add(seg["width"])
            power_nets[net]["track_count"] += 1
            dx = seg["x2"] - seg["x1"]
            dy = seg["y2"] - seg["y1"]
            power_nets[net]["total_length_mm"] += math.sqrt(dx * dx + dy * dy)

    result = []
    for net_num, info in sorted(power_nets.items(), key=lambda x: x[1]["name"]):
        if info["track_count"] == 0:
            continue  # Only zone-routed or single-pad
        widths = sorted(info["widths"])
        result.append({
            "net": info["name"],
            "track_count": info["track_count"],
            "total_length_mm": round(info["total_length_mm"], 2),
            "min_width_mm": widths[0] if widths else None,
            "max_width_mm": widths[-1] if widths else None,
            "widths_used": widths,
        })
    return result


def analyze_decoupling_placement(footprints: list[dict]) -> list[dict]:
    """For each IC, find nearby capacitors and report distances.

    Helps verify decoupling caps are placed close to IC power pins.
    """
    ics = [fp for fp in footprints if re.match(r'^U\d', fp.get("reference", ""))]
    caps = [fp for fp in footprints if re.match(r'^C\d', fp.get("reference", ""))]

    if not ics or not caps:
        return []

    results = []
    for ic in ics:
        ix, iy = ic["x"], ic["y"]
        nearby = []
        for cap in caps:
            cx, cy = cap["x"], cap["y"]
            dist = math.sqrt((ix - cx) ** 2 + (iy - cy) ** 2)
            if dist <= 10.0:  # Within 10mm
                # Check if cap shares a net with IC (likely decoupling)
                ic_nets = {p.get("net_name") for p in ic.get("pads", []) if p.get("net_name")}
                cap_nets = {p.get("net_name") for p in cap.get("pads", []) if p.get("net_name")}
                shared = ic_nets & cap_nets - {""}
                nearby.append({
                    "cap": cap["reference"],
                    "value": cap.get("value", ""),
                    "distance_mm": round(dist, 2),
                    "shared_nets": sorted(shared) if shared else [],
                    "same_side": cap["layer"] == ic["layer"],
                })
        if nearby:
            nearby.sort(key=lambda n: n["distance_mm"])
            results.append({
                "ic": ic["reference"],
                "value": ic.get("value", ""),
                "layer": ic["layer"],
                "nearby_caps": nearby,
                "closest_cap_mm": nearby[0]["distance_mm"],
            })
    return results


def analyze_connectivity_uf(footprints: list[dict], tracks: dict, vias: dict,
                            net_names: dict[int, str],
                            zones: list[dict] | None = None) -> dict:
    """Full union-find connectivity analysis.

    Instead of just checking "does this net have any tracks?", this builds
    actual point-to-point connectivity from pads, tracks, and vias to find
    nets that are partially routed (some pads connected, others not).
    """
    # For each net, build a union-find of connected points
    # Points are identified by (x, y, layer) tuples, snapped to 0.001mm grid

    def _snap(v: float) -> int:
        """Snap to 1µm grid to handle floating point issues."""
        return round(v * 1000)

    # Build per-net point sets
    net_points: dict[int, dict[tuple, int]] = {}  # net -> {point_key -> uf_id}
    net_parent: dict[int, dict[int, int]] = {}  # net -> {id -> parent}

    def _find(parents: dict[int, int], x: int) -> int:
        while parents[x] != x:
            parents[x] = parents[parents[x]]
            x = parents[x]
        return x

    def _union(parents: dict[int, int], a: int, b: int) -> None:
        ra, rb = _find(parents, a), _find(parents, b)
        if ra != rb:
            parents[ra] = rb

    def _get_id(net: int, point: tuple) -> int:
        if net not in net_points:
            net_points[net] = {}
            net_parent[net] = {}
        pts = net_points[net]
        if point not in pts:
            uid = len(pts)
            pts[point] = uid
            net_parent[net][uid] = uid
        return pts[point]

    # 1. Register pad locations
    pad_locs: dict[int, list[tuple[str, str]]] = {}  # net -> [(ref.pad, point_key)]
    for fp in footprints:
        for pad in fp.get("pads", []):
            net_num = pad.get("net_number", 0)
            if net_num <= 0:
                continue
            ax = _snap(pad.get("abs_x", 0))
            ay = _snap(pad.get("abs_y", 0))
            # Pads connect on all their layers
            pad_layers = pad.get("layers", [])
            for layer in pad_layers:
                if "Cu" in layer:
                    pt = (ax, ay, layer)
                    _get_id(net_num, pt)
            # For through-hole / vias (*.Cu), register on all copper layers
            if any(l.startswith("*.") for l in pad_layers):
                for layer in ["F.Cu", "B.Cu"]:
                    pt = (ax, ay, layer)
                    _get_id(net_num, pt)
            pad_locs.setdefault(net_num, []).append(
                (f"{fp['reference']}.{pad['number']}", (ax, ay)))

    # 2. Register and union track segments
    for seg in tracks.get("segments", []):
        net = seg["net"]
        if net <= 0:
            continue
        p1 = (_snap(seg["x1"]), _snap(seg["y1"]), seg["layer"])
        p2 = (_snap(seg["x2"]), _snap(seg["y2"]), seg["layer"])
        id1 = _get_id(net, p1)
        id2 = _get_id(net, p2)
        _union(net_parent[net], id1, id2)

    for arc in tracks.get("arcs", []):
        net = arc["net"]
        if net <= 0:
            continue
        s = arc["start"]
        e = arc["end"]
        p1 = (_snap(s[0]), _snap(s[1]), arc["layer"])
        p2 = (_snap(e[0]), _snap(e[1]), arc["layer"])
        id1 = _get_id(net, p1)
        id2 = _get_id(net, p2)
        _union(net_parent[net], id1, id2)

    # 3. Register and union vias (connect layers at the same XY)
    for via in vias.get("vias", []):
        net = via["net"]
        if net <= 0:
            continue
        vx = _snap(via["x"])
        vy = _snap(via["y"])
        via_layers = via.get("layers", ["F.Cu", "B.Cu"])
        prev_id = None
        for layer in via_layers:
            pt = (vx, vy, layer)
            vid = _get_id(net, pt)
            if prev_id is not None:
                _union(net_parent[net], prev_id, vid)
            prev_id = vid

    # 4. Account for zone connectivity
    # Copper zones connect all pads on the same net within the zone area.
    # Approximation: if a net has a zone on a layer, union ALL pads on that
    # net+layer (assumes zone covers all pads — accurate for power/ground
    # planes, may overcount for partial zones).
    # NOTE: ZoneFills spatial data could improve this by checking if each
    # pad is within the zone outline, but thermal relief clearances around
    # pads mean point-in-fill tests would give false negatives. The zone
    # outline polygon (not the fill polygon) would be the right test here.
    if zones:
        zone_nets: dict[int, set[str]] = {}  # net_num -> set of zone layers
        for z in zones:
            zn = z.get("net", 0)
            if zn > 0:
                for zl in z.get("layers", []):
                    zone_nets.setdefault(zn, set()).add(zl)

        # Build pad lookup by net for zone registration
        _pad_by_net: dict[int, list[tuple[int, int, list[str]]]] = {}
        for fp in footprints:
            for pad in fp.get("pads", []):
                pnet = pad.get("net_number", 0)
                if pnet > 0 and pnet in zone_nets:
                    ax = _snap(pad.get("abs_x", 0))
                    ay = _snap(pad.get("abs_y", 0))
                    p_layers = pad.get("layers", [])
                    _pad_by_net.setdefault(pnet, []).append((ax, ay, p_layers))

        for net_num, z_layers in zone_nets.items():
            for zlayer in z_layers:
                # Register and union all pads on this net that are on the zone layer
                first_id = None
                for (ax, ay, p_layers) in _pad_by_net.get(net_num, []):
                    # Check if pad is on this zone layer
                    on_layer = (zlayer in p_layers or
                                any(l.startswith("*.") for l in p_layers))
                    if on_layer:
                        pt = (ax, ay, zlayer)
                        pid = _get_id(net_num, pt)
                        if first_id is not None:
                            _union(net_parent[net_num], first_id, pid)
                        else:
                            first_id = pid

                # Also union any track/via points on this layer
                if first_id is not None and net_num in net_points:
                    pts = net_points[net_num]
                    for (px, py, pl), pid in pts.items():
                        if pl == zlayer:
                            _union(net_parent[net_num], first_id, pid)

    # 5. Find unrouted / partially routed nets
    # For each net with ≥2 pads, check how many connected components exist
    unrouted = []
    partially_routed = []
    pad_nets: dict[int, list[str]] = {}
    for fp in footprints:
        for pad in fp.get("pads", []):
            net_num = pad.get("net_number", 0)
            if net_num > 0:
                pad_nets.setdefault(net_num, []).append(
                    f"{fp['reference']}.{pad['number']}")

    routed_count = 0
    for net_num, pads in pad_nets.items():
        if len(pads) < 2:
            continue

        if net_num not in net_points:
            # No routing at all for this net
            unrouted.append({
                "net_number": net_num,
                "net_name": net_names.get(net_num, f"net_{net_num}"),
                "pad_count": len(pads),
                "pads": pads,
                "status": "unrouted",
            })
            continue

        # Count connected components among pad points
        parents = net_parent[net_num]
        pts = net_points[net_num]
        # Find which component each pad belongs to
        pad_components = set()
        for pad_label, (px, py) in pad_locs.get(net_num, []):
            # Try to find this pad in the point map (check all copper layers)
            found = False
            for layer in ["F.Cu", "B.Cu", "In1.Cu", "In2.Cu", "In3.Cu", "In4.Cu"]:
                pt = (px, py, layer)
                if pt in pts:
                    pad_components.add(_find(parents, pts[pt]))
                    found = True
                    break
            if not found:
                # Pad not connected to any routing
                pad_components.add(-hash(pad_label))  # unique disconnected ID

        if len(pad_components) <= 1:
            routed_count += 1
        else:
            partially_routed.append({
                "net_number": net_num,
                "net_name": net_names.get(net_num, f"net_{net_num}"),
                "pad_count": len(pads),
                "connected_groups": len(pad_components),
                "pads": pads,
                "status": "partially_routed",
            })

    return {
        "total_nets_with_pads": len(pad_nets),
        "fully_routed": routed_count,
        "partially_routed_count": len(partially_routed),
        "unrouted_count": len(unrouted),
        "routing_complete": len(unrouted) == 0 and len(partially_routed) == 0,
        "unrouted": sorted(unrouted, key=lambda u: u["net_name"]),
        "partially_routed": sorted(partially_routed, key=lambda u: u["net_name"]),
    }


def analyze_net_lengths(tracks: dict, vias: dict,
                        net_names: dict[int, str]) -> list[dict]:
    """Per-net trace length measurement for matched-length and routing analysis.

    Provides total length, per-layer breakdown, segment count, and via count
    for each routed net. Enables differential pair matching, bus length matching,
    and routing completeness assessment by higher-level logic.
    """
    net_data: dict[int, dict] = {}

    for seg in tracks.get("segments", []):
        net = seg["net"]
        if net <= 0:
            continue
        dx = seg["x2"] - seg["x1"]
        dy = seg["y2"] - seg["y1"]
        length = math.sqrt(dx * dx + dy * dy)

        d = net_data.setdefault(net, {"layers": {}, "total_length": 0.0,
                                      "segment_count": 0, "via_count": 0})
        d["total_length"] += length
        d["segment_count"] += 1
        layer = seg["layer"]
        ld = d["layers"].setdefault(layer, {"length": 0.0, "segments": 0})
        ld["length"] += length
        ld["segments"] += 1

    for arc in tracks.get("arcs", []):
        net = arc["net"]
        if net <= 0:
            continue
        s, e = arc["start"], arc["end"]
        m = arc.get("mid")
        if m:
            length = _arc_length_3pt(s[0], s[1], m[0], m[1], e[0], e[1])
        else:
            dx, dy = e[0] - s[0], e[1] - s[1]
            length = math.sqrt(dx * dx + dy * dy)

        d = net_data.setdefault(net, {"layers": {}, "total_length": 0.0,
                                      "segment_count": 0, "via_count": 0})
        d["total_length"] += length
        d["segment_count"] += 1
        layer = arc["layer"]
        ld = d["layers"].setdefault(layer, {"length": 0.0, "segments": 0})
        ld["length"] += length
        ld["segments"] += 1

    for via in vias.get("vias", []):
        net = via["net"]
        if net <= 0:
            continue
        d = net_data.setdefault(net, {"layers": {}, "total_length": 0.0,
                                      "segment_count": 0, "via_count": 0})
        d["via_count"] += 1

    result = []
    for net_num, data in sorted(net_data.items(),
                                key=lambda x: x[1]["total_length"], reverse=True):
        result.append({
            "net": net_names.get(net_num, f"net_{net_num}"),
            "net_number": net_num,
            "total_length_mm": round(data["total_length"], 3),
            "segment_count": data["segment_count"],
            "via_count": data["via_count"],
            "layers": {
                layer: {"length_mm": round(info["length"], 3),
                        "segments": info["segments"]}
                for layer, info in sorted(data["layers"].items())
            },
        })
    return result


def analyze_ground_domains(footprints: list[dict], net_names: dict[int, str],
                           zones: list[dict]) -> dict:
    """Identify ground domain splits and component membership.

    Detects separate ground nets (GND, AGND, DGND, PGND, etc.) and reports
    which components connect to each. Components on multiple ground domains
    are flagged — these may be intentional (star ground) or errors.
    """
    ground_nets: dict[int, str] = {}
    for net_num, name in net_names.items():
        nu = name.upper()
        if any(g in nu for g in ("GND", "VSS", "GROUND")):
            ground_nets[net_num] = name

    if not ground_nets:
        return {"domain_count": 0, "domains": [], "multi_domain_components": []}

    domain_components: dict[int, set[str]] = {n: set() for n in ground_nets}
    component_domains: dict[str, set[int]] = {}

    for fp in footprints:
        ref = fp.get("reference", "")
        for pad in fp.get("pads", []):
            net_num = pad.get("net_number", 0)
            if net_num in ground_nets:
                domain_components[net_num].add(ref)
                component_domains.setdefault(ref, set()).add(net_num)

    ground_zones: dict[int, list[str]] = {}
    for z in zones:
        zn = z.get("net", 0)
        if zn in ground_nets:
            ground_zones.setdefault(zn, []).extend(z.get("layers", []))

    domains = []
    for net_num, name in sorted(ground_nets.items(), key=lambda x: x[1]):
        comps = sorted(domain_components.get(net_num, set()))
        domains.append({
            "net": name,
            "net_number": net_num,
            "component_count": len(comps),
            "components": comps,
            "has_zone": net_num in ground_zones,
            "zone_layers": sorted(set(ground_zones.get(net_num, []))),
        })

    multi = []
    for ref, nets in sorted(component_domains.items()):
        if len(nets) > 1:
            multi.append({
                "component": ref,
                "ground_nets": sorted(ground_nets[n] for n in nets),
            })

    return {
        "domain_count": len(domains),
        "domains": domains,
        "multi_domain_components": multi,
    }


def analyze_trace_proximity(tracks: dict, net_names: dict[int, str],
                            grid_size: float = 0.5) -> dict:
    """Identify signal nets with traces running close together on the same layer.

    Uses a spatial grid to find net pairs sharing grid cells, indicating
    physical proximity on the PCB. Power/ground nets are excluded since
    they are expected to be everywhere. Only pairs with significant coupling
    (≥2 shared cells) are reported.

    Returns proximity pairs sorted by approximate coupling length, plus the
    grid resolution used. Higher-level logic can use this to assess crosstalk
    risk, guard trace needs, or impedance concerns.
    """
    grid: dict[tuple[str, int, int], set[int]] = {}

    def _mark(x1: float, y1: float, x2: float, y2: float,
              layer: str, net: int) -> None:
        if net <= 0:
            return
        dx, dy = x2 - x1, y2 - y1
        length = math.sqrt(dx * dx + dy * dy)
        if length < 0.001:
            return
        steps = max(1, int(length / (grid_size * 0.5)))
        inv = 1.0 / steps
        for i in range(steps + 1):
            t = i * inv
            gx = int((x1 + t * dx) / grid_size)
            gy = int((y1 + t * dy) / grid_size)
            grid.setdefault((layer, gx, gy), set()).add(net)

    for seg in tracks.get("segments", []):
        _mark(seg["x1"], seg["y1"], seg["x2"], seg["y2"],
              seg["layer"], seg["net"])
    for arc in tracks.get("arcs", []):
        s, e = arc["start"], arc["end"]
        _mark(s[0], s[1], e[0], e[1], arc["layer"], arc["net"])

    # Count shared cells per net pair (signal nets only)
    pair_counts: dict[tuple[str, int, int], int] = {}
    for (_layer, _gx, _gy), nets in grid.items():
        signal = sorted(n for n in nets
                        if not _is_power_ground_net(net_names.get(n, "")))
        if len(signal) < 2:
            continue
        for i in range(len(signal)):
            for j in range(i + 1, len(signal)):
                pk = (_layer, signal[i], signal[j])
                pair_counts[pk] = pair_counts.get(pk, 0) + 1

    pairs = []
    for (layer, na, nb), count in pair_counts.items():
        if count < 2:
            continue
        pairs.append({
            "net_a": net_names.get(na, f"net_{na}"),
            "net_b": net_names.get(nb, f"net_{nb}"),
            "layer": layer,
            "shared_cells": count,
            "approx_coupling_mm": round(count * grid_size, 1),
        })

    pairs.sort(key=lambda p: p["approx_coupling_mm"], reverse=True)

    return {
        "grid_size_mm": grid_size,
        "proximity_pairs": pairs[:100],
        "total_pairs_found": len(pairs),
    }


def analyze_current_capacity(tracks: dict, vias: dict, zones: list[dict],
                             net_names: dict[int, str],
                             setup: dict) -> dict:
    """Provide facts for current capacity assessment (IPC-2221).

    For each net, reports the minimum track width and total copper cross-section
    data that higher-level logic needs to calculate current capacity using
    IPC-2221 formulas. Also reports via drill sizes per net (vias have lower
    current capacity than tracks of the same width).

    Focuses on power/ground nets where current capacity matters most, but
    also flags any signal net with unusually thin traces for its track count
    (potential bottleneck).
    """
    # Per-net track width data
    net_widths: dict[int, dict] = {}

    for seg in tracks.get("segments", []):
        net = seg["net"]
        if net <= 0:
            continue
        w = seg["width"]
        layer = seg["layer"]
        d = net_widths.setdefault(net, {
            "min_width": float("inf"), "max_width": 0.0,
            "widths": set(), "layers": set(), "segment_count": 0,
            "via_count": 0, "via_drills": set(),
        })
        d["min_width"] = min(d["min_width"], w)
        d["max_width"] = max(d["max_width"], w)
        d["widths"].add(w)
        d["layers"].add(layer)
        d["segment_count"] += 1

    for arc in tracks.get("arcs", []):
        net = arc["net"]
        if net <= 0:
            continue
        w = arc["width"]
        d = net_widths.setdefault(net, {
            "min_width": float("inf"), "max_width": 0.0,
            "widths": set(), "layers": set(), "segment_count": 0,
            "via_count": 0, "via_drills": set(),
        })
        d["min_width"] = min(d["min_width"], w)
        d["max_width"] = max(d["max_width"], w)
        d["widths"].add(w)
        d["layers"].add(arc["layer"])
        d["segment_count"] += 1

    for via in vias.get("vias", []):
        net = via["net"]
        if net <= 0:
            continue
        d = net_widths.setdefault(net, {
            "min_width": float("inf"), "max_width": 0.0,
            "widths": set(), "layers": set(), "segment_count": 0,
            "via_count": 0, "via_drills": set(),
        })
        d["via_count"] += 1
        if via.get("drill"):
            d["via_drills"].add(via["drill"])

    # Zone coverage per net
    net_zones: dict[int, list[dict]] = {}
    for z in zones:
        zn = z.get("net", 0)
        if zn > 0:
            net_zones.setdefault(zn, []).append({
                "layers": z.get("layers", []),
                "filled_area_mm2": z.get("filled_area_mm2"),
                "min_thickness": z.get("min_thickness"),
            })

    # Board thickness for internal layer calculation
    board_thickness = setup.get("board_thickness_mm", 1.6)

    # Build output — power/ground nets first, then any signal nets with
    # narrow traces (potential current bottlenecks)
    power_entries = []
    signal_narrow = []

    for net_num, data in net_widths.items():
        if data["min_width"] == float("inf"):
            continue
        name = net_names.get(net_num, f"net_{net_num}")
        is_power = _is_power_ground_net(name)

        entry = {
            "net": name,
            "net_number": net_num,
            "min_track_width_mm": data["min_width"],
            "max_track_width_mm": data["max_width"],
            "track_widths_used": sorted(data["widths"]),
            "copper_layers": sorted(data["layers"]),
            "segment_count": data["segment_count"],
            "via_count": data["via_count"],
        }
        if data["via_drills"]:
            entry["via_drill_sizes_mm"] = sorted(data["via_drills"])

        if net_num in net_zones:
            entry["zones"] = net_zones[net_num]

        if is_power:
            power_entries.append(entry)
        elif data["min_width"] <= 0.15 and data["segment_count"] >= 5:
            # Signal nets with ≤0.15mm traces and significant routing
            signal_narrow.append(entry)

    power_entries.sort(key=lambda e: e["net"])
    signal_narrow.sort(key=lambda e: e["min_track_width_mm"])

    return {
        "board_thickness_mm": board_thickness,
        "power_ground_nets": power_entries,
        "narrow_signal_nets": signal_narrow[:20],
    }


def analyze_thermal_vias(footprints: list[dict], vias: dict,
                         zones: list[dict]) -> dict:
    """Provide facts for thermal analysis — via stitching, thermal pads, via-in-pad.

    Reports:
    - Via density per zone (stitching vias for thermal/ground plane connectivity)
    - Exposed/thermal pad detection on QFN/BGA packages (pad connected to ground)
    - Via clusters near thermal pads (thermal via arrays)
    - Overall via distribution across layers
    """
    zone_vias: dict[int, dict] = {}  # net_num -> via stats within zone
    # For each zone, count vias on the same net within the zone outline
    # (approximate: use bounding box of zone outline)
    zone_bounds: list[dict] = []
    for z in zones:
        zn = z.get("net", 0)
        if zn <= 0:
            continue
        # Use the outline_area as a proxy — if we had the actual outline
        # points we could do point-in-polygon, but for a first pass,
        # just count all vias on the same net
        zone_bounds.append({
            "net": zn,
            "net_name": z.get("net_name", ""),
            "layers": z.get("layers", []),
            "area_mm2": z.get("outline_area_mm2", 0),
            "filled_area_mm2": z.get("filled_area_mm2"),
        })

    # Count vias per net
    via_by_net: dict[int, list[dict]] = {}
    for via in vias.get("vias", []):
        net = via.get("net", 0)
        if net > 0:
            via_by_net.setdefault(net, []).append(via)

    # Zone stitching analysis
    stitching = []
    for zb in zone_bounds:
        net = zb["net"]
        net_vias = via_by_net.get(net, [])
        if not net_vias:
            continue
        # Compute via spacing statistics
        via_positions = [(v["x"], v["y"]) for v in net_vias]
        area = zb.get("area_mm2", 0)

        entry = {
            "net": zb["net_name"],
            "zone_layers": zb["layers"],
            "zone_area_mm2": round(area, 1) if area else None,
            "via_count": len(net_vias),
        }
        if area > 0:
            entry["via_density_per_cm2"] = round(len(net_vias) / (area / 100.0), 1)

        # Check drill sizes
        drills = set()
        for v in net_vias:
            if v.get("drill"):
                drills.add(v["drill"])
        if drills:
            entry["drill_sizes_mm"] = sorted(drills)

        stitching.append(entry)

    # Thermal pad detection — look for large center pads (pad 0 or EP)
    # on QFN/BGA/DFN packages
    thermal_pads = []
    for fp in footprints:
        ref = fp.get("reference", "")
        lib = fp.get("library", "").lower()

        # Skip component types that don't have thermal pads
        ref_prefix = ""
        for c in ref:
            if c.isalpha():
                ref_prefix += c
            else:
                break
        if ref_prefix in ("BT", "TP", "J"):
            continue

        # Compute average SMD pad area for this footprint to detect thermal pads
        # (thermal pads are typically the largest pad, at least 2x average)
        smd_pad_areas = []
        for pad in fp.get("pads", []):
            if pad.get("type") == "smd":
                pw = pad.get("width", 0)
                ph = pad.get("height", 0)
                pa = pw * ph
                if pa > 0:
                    smd_pad_areas.append(pa)
        avg_pad_area = sum(smd_pad_areas) / len(smd_pad_areas) if smd_pad_areas else 0

        for pad in fp.get("pads", []):
            pad_num = str(pad.get("number", ""))
            # Thermal/exposed pads are typically numbered 0, EP, or have large area
            is_ep = pad_num in ("0", "EP", "")
            w = pad.get("width", 0)
            h = pad.get("height", 0)
            pad_area = w * h

            # Only flag SMD pads that are genuine thermal pads:
            # - Must be SMD type
            # - Must be large enough (>4mm² if EP/0, >9mm² otherwise)
            # - Must be at least 2x the average pad area for this component
            #   (thermal pads are distinctly larger than signal pads)
            # - Must be on a ground or power net (thermal pads dissipate heat
            #   and are almost always connected to GND or a power plane)
            if pad.get("type") != "smd" or pad_area <= 4.0:
                continue
            if not (is_ep or pad_area > 9.0):
                continue
            if avg_pad_area > 0 and pad_area < avg_pad_area * 2.0:
                continue
            net_name = pad.get("net_name", "")
            net_upper = net_name.upper()
            is_power_or_gnd = (
                net_upper in ("GND", "VSS", "AGND", "DGND", "PGND", "VCC", "VDD",
                              "AVCC", "AVDD", "DVCC", "DVDD", "VBUS")
                or net_upper.startswith("+")
                or net_upper.startswith("V+")
                or "GND" in net_upper
                or "VCC" in net_upper
                or "VDD" in net_upper
            )
            if not is_power_or_gnd and not is_ep:
                continue

            ax = pad.get("abs_x", fp["x"])
            ay = pad.get("abs_y", fp["y"])

            # Count standalone vias near this thermal pad
            standalone_vias = 0
            for via in vias.get("vias", []):
                if via.get("net") == pad.get("net_number", -1):
                    dx = via["x"] - ax
                    dy = via["y"] - ay
                    if math.sqrt(dx * dx + dy * dy) < max(w, h) * 1.5:
                        standalone_vias += 1

            # Count thru_hole pads in the same footprint on the same
            # net — these are footprint-embedded thermal vias
            footprint_via_pads = 0
            pad_net = pad.get("net_number", -1)
            for other_pad in fp.get("pads", []):
                if other_pad is pad:
                    continue
                if (other_pad.get("type") == "thru_hole" and
                        other_pad.get("net_number", -2) == pad_net and
                        pad_net >= 0):
                    footprint_via_pads += 1

            thermal_pads.append({
                "component": ref,
                "pad": pad_num,
                "pad_size_mm": [round(w, 2), round(h, 2)],
                "pad_area_mm2": round(pad_area, 2),
                "net": net_name,
                "nearby_thermal_vias": standalone_vias + footprint_via_pads,
                "standalone_vias": standalone_vias,
                "footprint_via_pads": footprint_via_pads,
                "layer": fp.get("layer", "F.Cu"),
            })

    return {
        "zone_stitching": stitching,
        "thermal_pads": thermal_pads,
    }


def analyze_vias(vias: dict, footprints: list[dict],
                 net_names: dict[int, str]) -> dict:
    """Comprehensive via analysis — types, annular ring, via-in-pad, fanout, current.

    Reports:
    - Type breakdown: through-hole vs blind vs micro via counts and distributions
    - Annular ring: (pad_size - drill) / 2 per via, with min/max/distribution
    - Via-in-pad detection: vias located within footprint pad bounding boxes
    - Fanout pattern detection: clusters of vias near BGA/QFN pads
    - Current capacity facts: drill sizes mapped to IPC-2221 approximate ratings
    """
    all_vias = vias.get("vias", [])
    if not all_vias:
        return {}

    # --- Type breakdown ---
    type_counts: dict[str, int] = {"through": 0, "blind": 0, "micro": 0}
    type_sizes: dict[str, dict[str, int]] = {
        "through": {}, "blind": {}, "micro": {},
    }
    for v in all_vias:
        vtype = v.get("type", "through") or "through"
        # Normalize — KiCad stores "blind" or "micro" as keywords
        if vtype not in type_counts:
            vtype = "through"
        type_counts[vtype] += 1
        key = f"{v['size']}/{v['drill']}"
        type_sizes[vtype][key] = type_sizes[vtype].get(key, 0) + 1

    type_breakdown = {}
    for vtype, count in type_counts.items():
        if count > 0:
            type_breakdown[vtype] = {
                "count": count,
                "size_distribution": type_sizes[vtype],
            }

    # --- Annular ring analysis ---
    rings: list[float] = []
    ring_dist: dict[float, int] = {}
    for v in all_vias:
        size = v.get("size", 0)
        drill = v.get("drill", 0)
        if size > 0 and drill > 0:
            ring = round((size - drill) / 2.0, 3)
            rings.append(ring)
            ring_dist[ring] = ring_dist.get(ring, 0) + 1

    annular_ring: dict = {}
    if rings:
        min_ring = min(rings)
        annular_ring = {
            "min_mm": min_ring,
            "max_mm": max(rings),
            "distribution": {str(k): cnt for k, cnt in sorted(ring_dist.items())},
        }
        # Count vias below common manufacturer minimums
        violations_0125 = sum(1 for r in rings if r < 0.125)
        violations_0100 = sum(1 for r in rings if r < 0.100)
        if violations_0125 > 0:
            annular_ring["below_0.125mm"] = violations_0125
        if violations_0100 > 0:
            annular_ring["below_0.100mm"] = violations_0100

    # --- Via-in-pad detection ---
    # Build spatial index of pads for efficient lookup
    via_in_pad: list[dict] = []
    # Collect all SMD pads with bounding boxes
    pad_boxes: list[dict] = []
    for fp in footprints:
        ref = fp.get("reference", "")
        fp_layer = fp.get("layer", "F.Cu")
        for pad in fp.get("pads", []):
            if pad.get("type") != "smd":
                continue
            ax = pad.get("abs_x")
            ay = pad.get("abs_y")
            pw = pad.get("width", 0)
            ph = pad.get("height", 0)
            if ax is None or ay is None or pw <= 0 or ph <= 0:
                continue
            pad_boxes.append({
                "ref": ref,
                "pad": pad.get("number", ""),
                "cx": ax, "cy": ay,
                "hw": pw / 2.0, "hh": ph / 2.0,
                "net": pad.get("net_number", -1),
                "layer": fp_layer,
            })

    for v in all_vias:
        vx, vy = v["x"], v["y"]
        v_net = v.get("net", 0)
        v_layers = v.get("layers", ["F.Cu", "B.Cu"])
        for pb in pad_boxes:
            # Via must be on the same copper layer as the pad
            if pb["layer"] not in v_layers:
                continue
            if (abs(vx - pb["cx"]) <= pb["hw"] and
                    abs(vy - pb["cy"]) <= pb["hh"]):
                same_net = v_net == pb["net"]
                via_in_pad.append({
                    "component": pb["ref"],
                    "pad": pb["pad"],
                    "via_x": round(vx, 3),
                    "via_y": round(vy, 3),
                    "via_drill": v.get("drill", 0),
                    "same_net": same_net,
                    "via_type": v.get("type", "through") or "through",
                })
                break  # Each via counted once

    # --- Fanout pattern detection ---
    # BGA/QFN packages with many pads often have fanout vias —
    # clusters of vias immediately outside the component footprint
    fanout_patterns: list[dict] = []
    for fp in footprints:
        pad_count = fp.get("pad_count", 0)
        if pad_count < 16:
            continue  # Only check multi-pad packages
        ref = fp.get("reference", "")
        lib = fp.get("library", "").lower()

        # Determine if this is a BGA/QFN/QFP-like package
        is_area_array = any(kw in lib for kw in
                           ("bga", "qfn", "dfn", "qfp", "lga", "wlcsp",
                            "son", "vson", "tqfp", "lqfp"))
        if not is_area_array and pad_count < 40:
            continue

        # Get component bounding box from courtyard or pad extents
        crtyd = fp.get("courtyard")
        if crtyd:
            cx_min, cy_min = crtyd["min_x"], crtyd["min_y"]
            cx_max, cy_max = crtyd["max_x"], crtyd["max_y"]
        else:
            # Fall back to pad extents
            pxs = [p.get("abs_x", fp["x"]) for p in fp.get("pads", [])]
            pys = [p.get("abs_y", fp["y"]) for p in fp.get("pads", [])]
            if not pxs:
                continue
            margin = 0.5
            cx_min, cx_max = min(pxs) - margin, max(pxs) + margin
            cy_min, cy_max = min(pys) - margin, max(pys) + margin

        # Expand by 2mm to catch fanout vias just outside the component
        expand = 2.0
        fx_min = cx_min - expand
        fx_max = cx_max + expand
        fy_min = cy_min - expand
        fy_max = cy_max + expand

        # Count vias in the expanded zone but outside the courtyard
        fanout_vias = 0
        fanout_nets: set[int] = set()
        for v in all_vias:
            vx, vy = v["x"], v["y"]
            if fx_min <= vx <= fx_max and fy_min <= vy <= fy_max:
                # Outside courtyard (actual fanout) or inside (via-in-pad)
                fanout_vias += 1
                if v.get("net", 0) > 0:
                    fanout_nets.add(v["net"])

        if fanout_vias >= 4:
            fanout_patterns.append({
                "component": ref,
                "pad_count": pad_count,
                "fanout_vias": fanout_vias,
                "unique_nets": len(fanout_nets),
                "package": fp.get("library", ""),
            })

    fanout_patterns.sort(key=lambda e: e["fanout_vias"], reverse=True)

    # --- Current capacity facts ---
    # IPC-2221 approximate via current capacity (1oz copper, 10°C rise)
    # Based on plated barrel: I ≈ k * d * t where d=drill, t=plating thickness
    # Typical 1oz plating ~25µm. These are conservative approximations.
    drill_sizes: dict[float, int] = {}
    for v in all_vias:
        d = v.get("drill", 0)
        if d > 0:
            drill_sizes[d] = drill_sizes.get(d, 0) + 1

    current_facts: dict = {}
    if drill_sizes:
        min_drill = min(drill_sizes.keys())
        max_drill = max(drill_sizes.keys())
        current_facts = {
            "drill_size_distribution": {str(k): cnt for k, cnt
                                        in sorted(drill_sizes.items())},
            "min_drill_mm": min_drill,
            "max_drill_mm": max_drill,
            "total_vias": len(all_vias),
        }
        # Approximate current ratings for common drill sizes (25µm plating)
        ratings = []
        for d in sorted(drill_sizes.keys()):
            # Barrel cross-section = π * d * t (thin-wall cylinder)
            # Current ≈ cross_section_area * current_density
            # For 25µm plating: area_mm2 = π * d * 0.025
            area_mm2 = math.pi * d * 0.025
            # Approximate 1A per 0.003 mm² (conservative for 10°C rise)
            approx_amps = round(area_mm2 / 0.003, 1)
            ratings.append({
                "drill_mm": d,
                "count": drill_sizes[d],
                "plating_area_mm2": round(area_mm2, 4),
                "approx_current_A": approx_amps,
            })
        current_facts["ratings"] = ratings

    result: dict = {
        "type_breakdown": type_breakdown,
    }
    if annular_ring:
        result["annular_ring"] = annular_ring
    if via_in_pad:
        result["via_in_pad"] = via_in_pad
    if fanout_patterns:
        result["fanout_patterns"] = fanout_patterns
    if current_facts:
        result["current_capacity"] = current_facts

    return result


def extract_silkscreen(root: list, footprints: list[dict]) -> dict:
    """Extract silkscreen text and check documentation completeness.

    Reports:
    - Board-level text (gr_text on SilkS layers): project name, version, logos
    - Per-footprint reference and user text visibility on silk
    - Text on Fab layers (assembly reference)
    - Documentation audit: missing board name/revision, connector labels,
      switch on/off indicators, polarity markers, pin-1 indicators
    """
    # ---- Board-level silkscreen text ----
    board_texts = []
    for gt in find_all(root, "gr_text"):
        layer = get_value(gt, "layer")
        if not layer:
            continue
        if "SilkS" not in layer and "Silkscreen" not in layer:
            continue
        text = gt[1] if len(gt) > 1 and isinstance(gt[1], str) else ""
        at = get_at(gt)
        board_texts.append({
            "text": text,
            "layer": layer,
            "x": round(at[0], 2) if at else None,
            "y": round(at[1], 2) if at else None,
        })

    # Fab layer text (assembly reference)
    fab_texts = []
    for gt in find_all(root, "gr_text"):
        layer = get_value(gt, "layer")
        if not layer or "Fab" not in layer:
            continue
        text = gt[1] if len(gt) > 1 and isinstance(gt[1], str) else ""
        fab_texts.append({
            "text": text,
            "layer": layer,
        })

    # ---- Per-footprint silkscreen text analysis ----
    # Parse raw footprint nodes for fp_text / property visibility on silk layers
    fp_nodes = find_all(root, "footprint") or find_all(root, "module")

    refs_visible = 0
    refs_hidden = 0
    hidden_refs: list[str] = []
    values_on_silk: list[str] = []
    user_silk_texts: list[dict] = []

    for fp_node in fp_nodes:
        fp_ref = get_property(fp_node, "Reference") or ""
        if not fp_ref:
            for ft in find_all(fp_node, "fp_text"):
                if len(ft) >= 3 and ft[1] == "reference":
                    fp_ref = ft[2]
                    break

        # Check reference visibility on silk (KiCad 9: property nodes, KiCad 5-8: fp_text)
        ref_visible = False
        for prop in find_all(fp_node, "property"):
            if len(prop) >= 3 and prop[1] == "Reference":
                layer = get_value(prop, "layer")
                if layer and ("SilkS" in layer or "Silkscreen" in layer):
                    # Check if hidden via (effects (font ...) hide)
                    effects = find_first(prop, "effects")
                    is_hidden = False
                    if effects:
                        for child in effects:
                            if child == "hide" or (isinstance(child, list) and child[0] == "hide"):
                                is_hidden = True
                                break
                    if not is_hidden:
                        ref_visible = True
                break

        # KiCad 5-8 fp_text check
        if not ref_visible:
            for ft in find_all(fp_node, "fp_text"):
                if len(ft) >= 3 and ft[1] == "reference":
                    layer = get_value(ft, "layer")
                    if layer and ("SilkS" in layer or "Silkscreen" in layer):
                        effects = find_first(ft, "effects")
                        is_hidden = False
                        if effects:
                            for child in effects:
                                if child == "hide" or (isinstance(child, list) and child[0] == "hide"):
                                    is_hidden = True
                                    break
                        if not is_hidden:
                            ref_visible = True
                    break

        if ref_visible:
            refs_visible += 1
        else:
            refs_hidden += 1
            if fp_ref:
                hidden_refs.append(fp_ref)

        # Check for value text visible on silk (common mistake — clutters board)
        for ft in find_all(fp_node, "fp_text"):
            if len(ft) >= 3 and ft[1] == "value":
                layer = get_value(ft, "layer")
                if layer and ("SilkS" in layer or "Silkscreen" in layer):
                    effects = find_first(ft, "effects")
                    is_hidden = False
                    if effects:
                        for child in effects:
                            if child == "hide" or (isinstance(child, list) and child[0] == "hide"):
                                is_hidden = True
                                break
                    if not is_hidden and fp_ref:
                        values_on_silk.append(fp_ref)

        # Also check property nodes for value on silk (KiCad 9)
        for prop in find_all(fp_node, "property"):
            if len(prop) >= 3 and prop[1] == "Value":
                layer = get_value(prop, "layer")
                if layer and ("SilkS" in layer or "Silkscreen" in layer):
                    effects = find_first(prop, "effects")
                    is_hidden = False
                    if effects:
                        for child in effects:
                            if child == "hide" or (isinstance(child, list) and child[0] == "hide"):
                                is_hidden = True
                                break
                    if not is_hidden and fp_ref and fp_ref not in values_on_silk:
                        values_on_silk.append(fp_ref)

        # Collect user-placed silk text within footprints (fp_text user "...")
        for ft in find_all(fp_node, "fp_text"):
            if len(ft) >= 3 and ft[1] == "user":
                layer = get_value(ft, "layer")
                if layer and ("SilkS" in layer or "Silkscreen" in layer):
                    effects = find_first(ft, "effects")
                    is_hidden = False
                    if effects:
                        for child in effects:
                            if child == "hide" or (isinstance(child, list) and child[0] == "hide"):
                                is_hidden = True
                                break
                    if not is_hidden:
                        user_silk_texts.append({
                            "footprint": fp_ref,
                            "text": ft[2],
                        })

    # ---- Documentation audit ----
    # Combine all visible silk text for checking
    all_silk_text = [t["text"] for t in board_texts]
    all_silk_text.extend(t["text"] for t in user_silk_texts)
    all_silk_upper = " ".join(t.upper() for t in all_silk_text)

    documentation_warnings = []

    # Check for board name / project name on silk
    has_board_name = False
    for t in board_texts:
        txt = t["text"].upper()
        # Common board name patterns: not just "REF**" or coordinates
        if txt and txt not in ("REF**", "${REFERENCE}") and len(txt) >= 3:
            has_board_name = True
            break
    if not has_board_name:
        documentation_warnings.append({
            "type": "missing_board_name",
            "severity": "suggestion",
            "message": "No board name or project identifier found in silkscreen text. "
                       "Consider adding the board name for easy identification.",
        })

    # Check for revision marking
    has_revision = any(
        any(kw in t.upper() for kw in ("REV", "V1", "V2", "V3", "R0", "R1", "VER"))
        for t in all_silk_text
    )
    if not has_revision:
        documentation_warnings.append({
            "type": "missing_revision",
            "severity": "warning",
            "message": "No revision marking found in silkscreen. "
                       "Add a revision label (e.g., 'Rev A', 'V1.0') to track board versions.",
        })

    # ---- Component-specific documentation checks ----
    # Build lookup of which footprints have user silk text nearby
    fp_user_texts: dict[str, list[str]] = {}
    for ut in user_silk_texts:
        fp_user_texts.setdefault(ut["footprint"], []).append(ut["text"].upper())

    # Classify footprints by type for targeted checks
    switches = []
    connectors = []
    polarized = []  # LEDs, electrolytic caps, diodes
    test_points = []

    for fp in footprints:
        ref = fp.get("reference", "")
        lib = fp.get("library", "").lower()
        val = fp.get("value", "").lower()

        if not ref:
            continue
        prefix = ""
        for c in ref:
            if c.isalpha():
                prefix += c
            else:
                break

        if prefix in ("SW", "S", "BUT"):
            switches.append(ref)
        elif prefix in ("J", "P", "CN"):
            connectors.append(ref)
        elif prefix in ("D", "LED"):
            polarized.append(ref)
        elif prefix == "BT":
            polarized.append(ref)
        elif prefix == "TP":
            test_points.append(ref)
        elif prefix in ("C",):
            # Check if it's a polarized cap (electrolytic/tantalum)
            if any(kw in lib for kw in ("cp", "polarized", "elec", "tant")):
                polarized.append(ref)
            elif any(kw in val for kw in ("elec", "tant", "polarized")):
                polarized.append(ref)

    # Switches: check for on/off or function labels
    switches_without_labels = []
    for ref in switches:
        texts = fp_user_texts.get(ref, [])
        has_label = any(
            any(kw in t for kw in ("ON", "OFF", "RESET", "BOOT", "PWR", "POWER",
                                    "PUSH", "SW", "PROG", "FUNC", "MODE"))
            for t in texts
        )
        # Also check board-level texts near the switch
        if not has_label:
            switches_without_labels.append(ref)

    if switches_without_labels:
        documentation_warnings.append({
            "type": "missing_switch_labels",
            "severity": "warning",
            "components": switches_without_labels,
            "message": f"Switches without function labels on silkscreen: {switches_without_labels}. "
                       "Add ON/OFF, RESET, BOOT, or function description near each switch.",
        })

    # Connectors: check for pin-1 / signal name labels
    connectors_without_labels = []
    for ref in connectors:
        texts = fp_user_texts.get(ref, [])
        # Connectors with 3+ pins should have some labeling
        fp_data = next((f for f in footprints if f.get("reference") == ref), None)
        if fp_data and fp_data.get("pad_count", 0) >= 3:
            if not texts:
                connectors_without_labels.append(ref)

    if connectors_without_labels:
        documentation_warnings.append({
            "type": "missing_connector_labels",
            "severity": "suggestion",
            "components": connectors_without_labels,
            "message": f"Connectors (3+ pins) without silkscreen labels: {connectors_without_labels}. "
                       "Consider adding pin names, signal names, or connector function labels.",
        })

    # Polarized components: polarity markers are usually in the footprint itself
    # (dot, line, +/-) but we flag if there are many polarized parts for awareness
    if len(polarized) > 3:
        documentation_warnings.append({
            "type": "polarity_reminder",
            "severity": "info",
            "components": polarized,
            "message": f"{len(polarized)} polarized components (LEDs, diodes, batteries, "
                       "electrolytic caps). Verify polarity markers are visible on silkscreen.",
        })

    # ---- Assemble result ----
    result: dict = {
        "board_text_count": len(board_texts),
        "refs_visible_on_silk": refs_visible,
        "refs_hidden_on_silk": refs_hidden,
    }
    if board_texts:
        result["board_texts"] = board_texts
    if fab_texts:
        result["fab_texts"] = fab_texts[:20]
    if hidden_refs:
        result["hidden_refs"] = sorted(hidden_refs)[:30]
    if values_on_silk:
        result["values_visible_on_silk"] = sorted(values_on_silk)
    if user_silk_texts:
        result["user_silk_texts"] = user_silk_texts[:30]
    if documentation_warnings:
        result["documentation_warnings"] = documentation_warnings

    return result


def analyze_placement(footprints: list[dict], outline: dict) -> dict:
    """Component placement analysis — courtyard overlaps and edge clearance.

    Reports:
    - Courtyard overlaps: pairs of components on the same side whose courtyard
      bounding boxes overlap (potential physical collision or assembly issue)
    - Edge clearance: components closest to board edges (flagged if <0.5mm)
    - Placement density per board side
    """
    # Courtyard overlap detection (AABB intersection, same side only)
    overlaps = []
    fp_with_cy = [(fp, fp["courtyard"]) for fp in footprints if fp.get("courtyard")]

    for i in range(len(fp_with_cy)):
        fp_a, cy_a = fp_with_cy[i]
        for j in range(i + 1, len(fp_with_cy)):
            fp_b, cy_b = fp_with_cy[j]
            # Only check components on the same side
            if fp_a["layer"] != fp_b["layer"]:
                continue
            # AABB overlap check
            if (cy_a["min_x"] < cy_b["max_x"] and cy_a["max_x"] > cy_b["min_x"] and
                    cy_a["min_y"] < cy_b["max_y"] and cy_a["max_y"] > cy_b["min_y"]):
                # Compute overlap area
                ox = min(cy_a["max_x"], cy_b["max_x"]) - max(cy_a["min_x"], cy_b["min_x"])
                oy = min(cy_a["max_y"], cy_b["max_y"]) - max(cy_a["min_y"], cy_b["min_y"])
                overlaps.append({
                    "component_a": fp_a["reference"],
                    "component_b": fp_b["reference"],
                    "layer": fp_a["layer"],
                    "overlap_mm2": round(ox * oy, 3),
                })

    overlaps.sort(key=lambda o: o["overlap_mm2"], reverse=True)

    # Edge clearance — distance from component center to nearest board edge
    edge_close: list[dict] = []
    bbox = outline.get("bounding_box")
    if bbox:
        bx_min, by_min = bbox["min_x"], bbox["min_y"]
        bx_max, by_max = bbox["max_x"], bbox["max_y"]
        for fp in footprints:
            if not fp.get("reference"):
                continue
            cx, cy = fp["x"], fp["y"]
            # Distance to nearest edge (simplified — board outline as rectangle)
            d_left = cx - bx_min
            d_right = bx_max - cx
            d_top = cy - by_min
            d_bottom = by_max - cy
            min_edge = min(d_left, d_right, d_top, d_bottom)

            # Use courtyard if available for tighter estimate
            if fp.get("courtyard"):
                cy_box = fp["courtyard"]
                min_edge = min(
                    cy_box["min_x"] - bx_min,
                    bx_max - cy_box["max_x"],
                    cy_box["min_y"] - by_min,
                    by_max - cy_box["max_y"],
                )

            if min_edge < 1.0:  # Flag components within 1mm of edge
                edge_close.append({
                    "component": fp["reference"],
                    "layer": fp["layer"],
                    "edge_clearance_mm": round(min_edge, 2),
                })

    edge_close.sort(key=lambda e: e["edge_clearance_mm"])

    # Placement density
    board_area = None
    if bbox:
        board_area = bbox["width"] * bbox["height"]

    front_count = sum(1 for fp in footprints if fp["layer"] == "F.Cu")
    back_count = sum(1 for fp in footprints if fp["layer"] == "B.Cu")

    density: dict = {}
    if board_area and board_area > 0:
        density["board_area_cm2"] = round(board_area / 100.0, 2)
        if front_count:
            density["front_density_per_cm2"] = round(front_count / (board_area / 100.0), 1)
        if back_count:
            density["back_density_per_cm2"] = round(back_count / (board_area / 100.0), 1)

    result: dict = {"density": density}
    if overlaps:
        result["courtyard_overlaps"] = overlaps[:50]
        result["overlap_count"] = len(overlaps)
    if edge_close:
        result["edge_clearance_warnings"] = edge_close[:20]

    return result


def analyze_layer_transitions(tracks: dict, vias: dict,
                               net_names: dict[int, str]) -> list[dict]:
    """Identify signal net layer transitions (via usage patterns).

    For ground return path analysis, higher-level logic needs to know which
    signal nets change layers and where. A via forces the return current to
    find a path between layers — if there's no nearby stitching via on the
    reference plane, the return current loop area increases, raising EMI.

    Reports per-net: which layers are used, how many vias, and whether the
    net uses more than one copper layer (indicating layer transitions).
    """
    net_layers: dict[int, dict] = {}

    for seg in tracks.get("segments", []):
        net = seg["net"]
        if net <= 0:
            continue
        d = net_layers.setdefault(net, {"layers": set(), "vias": []})
        d["layers"].add(seg["layer"])

    for arc in tracks.get("arcs", []):
        net = arc["net"]
        if net <= 0:
            continue
        d = net_layers.setdefault(net, {"layers": set(), "vias": []})
        d["layers"].add(arc["layer"])

    for via in vias.get("vias", []):
        net = via["net"]
        if net <= 0 or net not in net_layers:
            continue
        net_layers[net]["vias"].append({
            "x": via["x"], "y": via["y"],
            "layers": via.get("layers", ["F.Cu", "B.Cu"]),
            "drill": via.get("drill", 0),
        })

    # Only report nets with layer transitions (multi-layer routing)
    result = []
    for net_num, data in sorted(net_layers.items()):
        if len(data["layers"]) < 2:
            continue
        name = net_names.get(net_num, f"net_{net_num}")
        if _is_power_ground_net(name):
            continue  # Power/ground layer transitions are expected

        entry = {
            "net": name,
            "net_number": net_num,
            "copper_layers": sorted(data["layers"]),
            "layer_count": len(data["layers"]),
            "via_count": len(data["vias"]),
        }
        if data["vias"]:
            entry["via_positions"] = [
                {"x": round(v["x"], 2), "y": round(v["y"], 2),
                 "layers": v["layers"]}
                for v in data["vias"]
            ]
        result.append(entry)

    result.sort(key=lambda e: e["via_count"], reverse=True)
    return result


def compute_statistics(footprints: list[dict], tracks: dict, vias: dict,
                       zones: list[dict], outline: dict, connectivity: dict,
                       net_names: dict[int, str] | None = None) -> dict:
    """Compute summary statistics."""
    # Component side distribution
    front = sum(1 for fp in footprints if fp["layer"] == "F.Cu")
    back = sum(1 for fp in footprints if fp["layer"] == "B.Cu")

    # SMD vs through-hole
    smd = sum(1 for fp in footprints if fp["type"] == "smd")
    tht = sum(1 for fp in footprints if fp["type"] == "through_hole")

    # Total track length
    total_length = 0
    for seg in tracks.get("segments", []):
        dx = seg["x2"] - seg["x1"]
        dy = seg["y2"] - seg["y1"]
        total_length += math.sqrt(dx * dx + dy * dy)

    # Copper layer count — tracks, vias, and zones
    copper_layers = set()
    for seg in tracks.get("segments", []):
        if "Cu" in seg.get("layer", ""):
            copper_layers.add(seg["layer"])
    for via in vias.get("vias", []):
        for l in via.get("layers", []):
            if "Cu" in l:
                copper_layers.add(l)
    for zone in zones:
        for l in zone.get("layers", []):
            if "Cu" in l:
                copper_layers.add(l)

    return {
        "footprint_count": len(footprints),
        "front_side": front,
        "back_side": back,
        "smd_count": smd,
        "tht_count": tht,
        "copper_layers_used": len(copper_layers),
        "copper_layer_names": sorted(copper_layers),
        "track_segments": tracks["total_count"],
        "via_count": vias["count"],
        "zone_count": len(zones),
        "total_track_length_mm": round(total_length, 2),
        "board_width_mm": outline["bounding_box"]["width"] if outline.get("bounding_box") else None,
        "board_height_mm": outline["bounding_box"]["height"] if outline.get("bounding_box") else None,
        "net_count": sum(1 for v in (net_names or {}).values() if v),
        "routing_complete": connectivity.get("routing_complete", False),
        "unrouted_net_count": connectivity.get("unrouted_count", 0),
    }


def extract_board_metadata(root: list) -> dict:
    """Extract board-level metadata — title block, properties, paper size.

    Reports: title, revision, date, company, comments, board-level custom
    properties (e.g. COPYRIGHT, VERSION), and paper size.
    """
    result: dict = {}

    # Paper size
    paper = get_value(root, "paper")
    if paper:
        result["paper"] = paper

    # Title block
    tb = find_first(root, "title_block")
    if tb:
        for field in ("title", "date", "rev", "company"):
            val = get_value(tb, field)
            if val:
                result[field] = val
        # Comments (up to 9)
        for comment in find_all(tb, "comment"):
            if len(comment) >= 3:
                result.setdefault("comments", {})[comment[1]] = comment[2]

    # Board-level properties (KiCad 8+)
    for prop in find_all(root, "property"):
        if len(prop) >= 3 and isinstance(prop[1], str) and isinstance(prop[2], str):
            result.setdefault("properties", {})[prop[1]] = prop[2]

    return result


def extract_dimensions(root: list) -> list[dict]:
    """Extract dimension annotations (designer-placed measurements).

    These are verified measurements placed by the designer — connector spacing,
    board dimensions, mounting hole distances, etc.
    """
    dims = []
    for dim in find_all(root, "dimension"):
        dim_info: dict = {}

        # The measurement value (first numeric element after keyword)
        if len(dim) > 1:
            try:
                dim_info["value_mm"] = round(float(dim[1]), 3)
            except (ValueError, TypeError):
                pass

        layer = get_value(dim, "layer")
        if layer:
            dim_info["layer"] = layer

        # Dimension type (KiCad 8+)
        dtype = get_value(dim, "type")
        if dtype:
            dim_info["type"] = dtype

        # Text label
        gr_text = find_first(dim, "gr_text")
        if gr_text and len(gr_text) > 1:
            dim_info["text"] = gr_text[1]

        # Feature line endpoints (where the measurement spans)
        for feat in ("feature1", "feature2"):
            feat_node = find_first(dim, feat)
            if feat_node:
                pts = find_first(feat_node, "pts")
                if pts:
                    xys = find_all(pts, "xy")
                    if xys:
                        dim_info.setdefault("endpoints", []).append(
                            [round(float(xys[0][1]), 3),
                             round(float(xys[0][2]), 3)])

        if dim_info:
            dims.append(dim_info)
    return dims


def extract_groups(root: list) -> list[dict]:
    """Extract group definitions (designer-defined component/routing groups)."""
    groups = []
    for group in find_all(root, "group"):
        name = group[1] if len(group) > 1 and isinstance(group[1], str) else ""
        members_node = find_first(group, "members")
        member_count = 0
        if members_node:
            member_count = len([m for m in members_node[1:]
                                if isinstance(m, str)])
        if member_count > 0 or name:
            groups.append({
                "name": name,
                "member_count": member_count,
            })
    return groups


def extract_net_classes(root: list) -> list[dict]:
    """Extract net class definitions (KiCad 5 format — stored in PCB file).

    In KiCad 6+, net classes moved to .kicad_pro (JSON). This function handles
    the legacy format where they appear as (net_class ...) in the PCB.
    """
    classes = []
    for nc in find_all(root, "net_class"):
        if len(nc) < 3:
            continue
        name = nc[1]
        description = nc[2] if len(nc) > 2 and isinstance(nc[2], str) else ""

        info: dict = {"name": name}
        if description:
            info["description"] = description

        # Design rule values
        for key in ("clearance", "trace_width", "via_dia", "via_drill",
                     "uvia_dia", "uvia_drill"):
            val = get_value(nc, key)
            if val:
                info[key] = float(val)

        # Net assignments
        nets = []
        for item in find_all(nc, "add_net"):
            if len(item) > 1:
                nets.append(item[1])
        if nets:
            info["nets"] = nets
            info["net_count"] = len(nets)

        classes.append(info)
    return classes


def _extract_package_code(footprint_name: str) -> str:
    """Extract package size code from footprint library name.

    Recognizes patterns like:
    - "Capacitor_SMD:C_0402_1005Metric" -> "0402"
    - "Resistor_SMD:R_0201_0603Metric" -> "0201"
    - "Package_TO_SOT_SMD:SOT-23" -> ""
    """
    m = re.search(r'[_:](?:C|R|L)_(\d{4})_', footprint_name)
    if m:
        return m.group(1)
    # Also try bare pattern like "0402" or "0201" in the name
    m = re.search(r'(?:^|[_:])(\d{4})(?:_|$|Metric)', footprint_name)
    if m:
        code = m.group(1)
        if code in ("0201", "0402", "0603", "0805", "1206", "1210", "2512"):
            return code
    return ""


def analyze_dfm(footprints: list[dict], tracks: dict, vias: dict,
                board_outline: dict, design_rules: dict | None = None) -> dict:
    """Design for Manufacturing scoring against common fab capabilities.

    Compares actual design parameters against JLCPCB standard and advanced
    process limits. Reports a DFM tier ("standard", "advanced", or
    "challenging"), all violations with actual vs limit values, and key
    manufacturing metrics.

    Args:
        footprints: Extracted footprint list.
        tracks: Extracted track data (with segments, arcs, width_distribution).
        vias: Extracted via data.
        board_outline: Board outline with bounding_box.
        design_rules: Optional design rules from setup extraction.
    """
    # JLCPCB standard process limits (mm)
    LIMITS_STD = {
        "min_track_width": 0.127,      # 5 mil
        "min_track_spacing": 0.127,     # 5 mil
        "min_drill": 0.2,              # PTH drill
        "min_annular_ring": 0.125,     # via annular ring
        "max_board_width": 100.0,      # pricing threshold
        "max_board_height": 100.0,
        "min_board_dim": 10.0,         # handling minimum
    }
    # Advanced process limits
    LIMITS_ADV = {
        "min_track_width": 0.1,        # 4 mil
        "min_track_spacing": 0.1,      # 4 mil
        "min_drill": 0.15,
        "min_annular_ring": 0.1,
    }

    violations = []
    metrics: dict = {}

    # --- Track width analysis ---
    all_widths = []
    for seg in tracks.get("segments", []):
        all_widths.append(seg["width"])
    for arc in tracks.get("arcs", []):
        all_widths.append(arc["width"])

    if all_widths:
        min_width = min(all_widths)
        metrics["min_track_width_mm"] = min_width
        if min_width < LIMITS_ADV["min_track_width"]:
            violations.append({
                "parameter": "track_width",
                "actual_mm": min_width,
                "standard_limit_mm": LIMITS_STD["min_track_width"],
                "advanced_limit_mm": LIMITS_ADV["min_track_width"],
                "tier_required": "challenging",
                "message": f"Track width {min_width}mm is below advanced process "
                           f"minimum ({LIMITS_ADV['min_track_width']}mm)",
            })
        elif min_width < LIMITS_STD["min_track_width"]:
            violations.append({
                "parameter": "track_width",
                "actual_mm": min_width,
                "standard_limit_mm": LIMITS_STD["min_track_width"],
                "advanced_limit_mm": LIMITS_ADV["min_track_width"],
                "tier_required": "advanced",
                "message": f"Track width {min_width}mm requires advanced process "
                           f"(standard minimum: {LIMITS_STD['min_track_width']}mm)",
            })

    # --- Track spacing analysis (approximate from segment proximity) ---
    # Build spatial grid to find close tracks on the same layer
    segments = tracks.get("segments", [])
    if len(segments) > 1:
        min_spacing = float("inf")
        # Sample endpoints and check distances between different-net segments on same layer
        # Group by layer for efficiency
        layer_segs: dict[str, list] = {}
        for seg in segments:
            layer_segs.setdefault(seg["layer"], []).append(seg)

        for layer, segs in layer_segs.items():
            if len(segs) < 2:
                continue
            # For large designs, limit sampling to keep runtime reasonable
            sample = segs if len(segs) <= 2000 else segs[:2000]
            for i in range(len(sample)):
                si = sample[i]
                for j in range(i + 1, min(i + 50, len(sample))):
                    sj = sample[j]
                    if si["net"] == sj["net"] or si["net"] == 0 or sj["net"] == 0:
                        continue
                    # Check endpoint-to-segment distance (simplified: endpoint-to-endpoint)
                    for (x1, y1) in [(si["x1"], si["y1"]), (si["x2"], si["y2"])]:
                        for (x2, y2) in [(sj["x1"], sj["y1"]), (sj["x2"], sj["y2"])]:
                            center_dist = math.sqrt((x1 - x2) ** 2 + (y1 - y2) ** 2)
                            # Edge-to-edge spacing = center distance - half widths
                            spacing = center_dist - (si["width"] + sj["width"]) / 2.0
                            if 0 <= spacing < min_spacing:
                                min_spacing = spacing

        if min_spacing < float("inf"):
            metrics["approx_min_spacing_mm"] = round(min_spacing, 4)
            if min_spacing < LIMITS_ADV["min_track_spacing"]:
                violations.append({
                    "parameter": "track_spacing",
                    "actual_mm": round(min_spacing, 4),
                    "standard_limit_mm": LIMITS_STD["min_track_spacing"],
                    "advanced_limit_mm": LIMITS_ADV["min_track_spacing"],
                    "tier_required": "challenging",
                    "message": f"Approximate track spacing {round(min_spacing, 4)}mm is below "
                               f"advanced process minimum ({LIMITS_ADV['min_track_spacing']}mm)",
                    "note": "Spacing is approximate (endpoint-to-endpoint, not full segment geometry)",
                })
            elif min_spacing < LIMITS_STD["min_track_spacing"]:
                violations.append({
                    "parameter": "track_spacing",
                    "actual_mm": round(min_spacing, 4),
                    "standard_limit_mm": LIMITS_STD["min_track_spacing"],
                    "advanced_limit_mm": LIMITS_ADV["min_track_spacing"],
                    "tier_required": "advanced",
                    "message": f"Approximate track spacing {round(min_spacing, 4)}mm requires "
                               f"advanced process (standard: {LIMITS_STD['min_track_spacing']}mm)",
                    "note": "Spacing is approximate (endpoint-to-endpoint, not full segment geometry)",
                })

    # --- Via drill analysis ---
    all_vias = vias.get("vias", [])
    if all_vias:
        drills = [v["drill"] for v in all_vias if v.get("drill", 0) > 0]
        if drills:
            min_drill = min(drills)
            metrics["min_drill_mm"] = min_drill
            if min_drill < LIMITS_ADV["min_drill"]:
                violations.append({
                    "parameter": "via_drill",
                    "actual_mm": min_drill,
                    "standard_limit_mm": LIMITS_STD["min_drill"],
                    "advanced_limit_mm": LIMITS_ADV["min_drill"],
                    "tier_required": "challenging",
                    "message": f"Via drill {min_drill}mm is below advanced process "
                               f"minimum ({LIMITS_ADV['min_drill']}mm)",
                })
            elif min_drill < LIMITS_STD["min_drill"]:
                violations.append({
                    "parameter": "via_drill",
                    "actual_mm": min_drill,
                    "standard_limit_mm": LIMITS_STD["min_drill"],
                    "advanced_limit_mm": LIMITS_ADV["min_drill"],
                    "tier_required": "advanced",
                    "message": f"Via drill {min_drill}mm requires advanced process "
                               f"(standard: {LIMITS_STD['min_drill']}mm)",
                })

    # --- Annular ring analysis ---
    if all_vias:
        rings = []
        for v in all_vias:
            size = v.get("size", 0)
            drill = v.get("drill", 0)
            if size > 0 and drill > 0:
                rings.append(round((size - drill) / 2.0, 3))
        if rings:
            min_ring = min(rings)
            metrics["min_annular_ring_mm"] = min_ring
            if min_ring < LIMITS_ADV["min_annular_ring"]:
                violations.append({
                    "parameter": "annular_ring",
                    "actual_mm": min_ring,
                    "standard_limit_mm": LIMITS_STD["min_annular_ring"],
                    "advanced_limit_mm": LIMITS_ADV["min_annular_ring"],
                    "tier_required": "challenging",
                    "message": f"Annular ring {min_ring}mm is below advanced process "
                               f"minimum ({LIMITS_ADV['min_annular_ring']}mm)",
                })
            elif min_ring < LIMITS_STD["min_annular_ring"]:
                violations.append({
                    "parameter": "annular_ring",
                    "actual_mm": min_ring,
                    "standard_limit_mm": LIMITS_STD["min_annular_ring"],
                    "advanced_limit_mm": LIMITS_ADV["min_annular_ring"],
                    "tier_required": "advanced",
                    "message": f"Annular ring {min_ring}mm requires advanced process "
                               f"(standard: {LIMITS_STD['min_annular_ring']}mm)",
                })

    # --- Board dimensions assessment ---
    bbox = board_outline.get("bounding_box")
    if bbox:
        width = bbox.get("width", 0)
        height = bbox.get("height", 0)
        metrics["board_width_mm"] = width
        metrics["board_height_mm"] = height

        if width > LIMITS_STD["max_board_width"] or height > LIMITS_STD["max_board_height"]:
            violations.append({
                "parameter": "board_size",
                "actual_mm": [width, height],
                "threshold_mm": [LIMITS_STD["max_board_width"],
                                 LIMITS_STD["max_board_height"]],
                "tier_required": "standard",
                "message": f"Board size {width}x{height}mm exceeds 100x100mm — "
                           f"higher fabrication pricing tier at JLCPCB",
            })

        if width < LIMITS_STD["min_board_dim"] and height < LIMITS_STD["min_board_dim"]:
            violations.append({
                "parameter": "board_size_small",
                "actual_mm": [width, height],
                "threshold_mm": LIMITS_STD["min_board_dim"],
                "tier_required": "standard",
                "message": f"Board size {width}x{height}mm is very small — "
                           f"may have handling concerns during fabrication",
            })

    # --- Determine overall DFM tier ---
    tier = "standard"
    for v in violations:
        req = v.get("tier_required", "standard")
        if req == "challenging":
            tier = "challenging"
            break
        elif req == "advanced" and tier != "challenging":
            tier = "advanced"

    result: dict = {
        "dfm_tier": tier,
        "metrics": metrics,
    }
    if violations:
        result["violations"] = violations
        result["violation_count"] = len(violations)
    else:
        result["violation_count"] = 0

    return result


def analyze_tombstoning_risk(footprints: list[dict], tracks: dict,
                             vias: dict,
                             zones: list[dict] | None = None) -> list[dict]:
    """Tombstoning risk assessment for small passive components.

    Tombstoning occurs when thermal asymmetry during reflow causes one pad
    of a small passive to lift off. Common causes:
    - One pad connected to a ground pour (high thermal mass), other to a
      thin signal trace
    - Asymmetric track widths connected to each pad
    - Proximity to thermal vias or large copper areas on one side

    Focuses on 0201 and 0402 passives (highest risk due to small size).

    Returns a list of at-risk components with risk level and reason.
    """
    # Identify small passive components
    small_passives = []
    for fp in footprints:
        if fp.get("dnp") or fp.get("board_only"):
            continue
        lib = fp.get("library", "")
        ref = fp.get("reference", "")
        # Must be a passive (C, R, L prefix)
        prefix = ""
        for c in ref:
            if c.isalpha():
                prefix += c
            else:
                break
        if prefix not in ("C", "R", "L"):
            continue

        pkg = _extract_package_code(lib)
        if pkg not in ("0201", "0402"):
            continue

        # Must have exactly 2 pads for tombstoning to apply
        pads = fp.get("pads", [])
        if len(pads) != 2:
            continue

        small_passives.append({
            "fp": fp,
            "package": pkg,
            "prefix": prefix,
        })

    if not small_passives:
        return []

    # Build net->zone mapping to identify ground pour connections
    zone_nets: set[int] = set()
    zone_net_layers: dict[int, set[str]] = {}
    if zones:
        for z in zones:
            zn = z.get("net", 0)
            if zn > 0:
                zone_nets.add(zn)
                for zl in z.get("layers", []):
                    zone_net_layers.setdefault(zn, set()).add(zl)

    # Build net->track width lookup from segments near each pad
    # For efficiency, build a lookup of track widths per net
    net_track_widths: dict[int, list[float]] = {}
    for seg in tracks.get("segments", []):
        net = seg["net"]
        if net > 0:
            net_track_widths.setdefault(net, []).append(seg["width"])
    for arc in tracks.get("arcs", []):
        net = arc["net"]
        if net > 0:
            net_track_widths.setdefault(net, []).append(arc["width"])

    # Analyze each small passive
    at_risk: list[dict] = []
    for sp in small_passives:
        fp = sp["fp"]
        pads = fp["pads"]
        pad_a = pads[0]
        pad_b = pads[1]

        net_a = pad_a.get("net_number", 0)
        net_b = pad_b.get("net_number", 0)
        net_name_a = pad_a.get("net_name", "")
        net_name_b = pad_b.get("net_name", "")

        risks: list[str] = []
        risk_level = "low"

        # Check 1: Ground pour asymmetry
        # If one pad is on a zone net and the other is not
        a_on_zone = net_a in zone_nets
        b_on_zone = net_b in zone_nets

        if a_on_zone != b_on_zone:
            # One pad has zone, the other doesn't — thermal asymmetry
            zone_pad = "pad 1" if a_on_zone else "pad 2"
            zone_net = net_name_a if a_on_zone else net_name_b
            risks.append(f"{zone_pad} connected to zone net ({zone_net}), "
                         f"other pad is signal-only — thermal asymmetry")
            risk_level = "high" if sp["package"] == "0201" else "medium"

        # Check 2: GND net on one pad, signal on other (common tombstone cause)
        a_is_gnd = _is_power_ground_net(net_name_a) and "GND" in net_name_a.upper()
        b_is_gnd = _is_power_ground_net(net_name_b) and "GND" in net_name_b.upper()
        if a_is_gnd != b_is_gnd:
            gnd_pad = "pad 1" if a_is_gnd else "pad 2"
            risks.append(f"{gnd_pad} is GND (likely ground pour), "
                         f"other pad is signal — thermal asymmetry risk")
            if risk_level == "low":
                risk_level = "medium"

        # Check 3: Track width asymmetry
        widths_a = net_track_widths.get(net_a, [])
        widths_b = net_track_widths.get(net_b, [])
        if widths_a and widths_b:
            avg_a = sum(widths_a) / len(widths_a)
            avg_b = sum(widths_b) / len(widths_b)
            if avg_a > 0 and avg_b > 0:
                ratio = max(avg_a, avg_b) / min(avg_a, avg_b)
                if ratio > 3.0:
                    risks.append(f"Track width asymmetry: pad 1 avg "
                                 f"{round(avg_a, 3)}mm vs pad 2 avg "
                                 f"{round(avg_b, 3)}mm (ratio {round(ratio, 1)}x)")
                    if risk_level == "low":
                        risk_level = "medium"

        # Check 4: Thermal via proximity (one pad near thermal vias)
        via_counts = [0, 0]
        for pad_idx, pad in enumerate([pad_a, pad_b]):
            px = pad.get("abs_x", fp["x"])
            py = pad.get("abs_y", fp["y"])
            for via in vias.get("vias", []):
                dx = via["x"] - px
                dy = via["y"] - py
                dist = math.sqrt(dx * dx + dy * dy)
                if dist < 1.0:  # Within 1mm
                    via_counts[pad_idx] += 1

        if via_counts[0] != via_counts[1] and max(via_counts) >= 2:
            more_pad = "pad 1" if via_counts[0] > via_counts[1] else "pad 2"
            risks.append(f"{more_pad} has {max(via_counts)} nearby vias vs "
                         f"{min(via_counts)} on other pad — thermal asymmetry")
            if risk_level == "low":
                risk_level = "medium"

        if risks:
            at_risk.append({
                "component": fp["reference"],
                "value": fp.get("value", ""),
                "package": sp["package"],
                "layer": fp.get("layer", "F.Cu"),
                "risk_level": risk_level,
                "pad_1_net": net_name_a,
                "pad_2_net": net_name_b,
                "reasons": risks,
            })

    # Sort by risk level (high first)
    risk_order = {"high": 0, "medium": 1, "low": 2}
    at_risk.sort(key=lambda r: (risk_order.get(r["risk_level"], 3),
                                r["component"]))
    return at_risk


def analyze_thermal_pad_vias(footprints: list[dict], vias: dict) -> list[dict]:
    """Thermal pad via adequacy assessment for QFN/BGA/DFN packages.

    For packages with exposed/thermal pads (large center pads), checks:
    - Number of vias within the thermal pad area
    - Via density (vias per mm²)
    - Whether vias are tented (solder mask prevents solder wicking)
    - Recommendations based on pad size

    Extends the existing thermal_vias analysis with per-component
    recommendations focused on via count and tenting.

    Returns a list of per-component thermal pad assessments.
    """
    all_vias = vias.get("vias", [])
    results: list[dict] = []

    for fp in footprints:
        if fp.get("dnp") or fp.get("board_only"):
            continue
        ref = fp.get("reference", "")
        if not ref:
            continue

        # Skip component types that don't have thermal pads
        ref_prefix = ""
        for c in ref:
            if c.isalpha():
                ref_prefix += c
            else:
                break
        if ref_prefix in ("BT", "TP", "J"):
            continue

        # Find thermal/exposed pads: large center SMD pads
        # Criteria: pad type is SMD, area > 4mm², and either named EP/0 or
        # the largest pad (by area) if it's significantly larger than others
        pads = fp.get("pads", [])
        if not pads:
            continue

        # Compute pad areas
        pad_areas: list[tuple[dict, float]] = []
        for pad in pads:
            if pad.get("type") != "smd":
                continue
            w = pad.get("width", 0)
            h = pad.get("height", 0)
            area = w * h
            if area > 0:
                pad_areas.append((pad, area))

        if not pad_areas:
            continue

        # Compute average SMD pad area for the 2x heuristic
        avg_pad_area = sum(a for _, a in pad_areas) / len(pad_areas) if pad_areas else 0

        # Find thermal pads
        thermal_pads_found: list[tuple[dict, float]] = []
        for pad, area in pad_areas:
            pad_num = str(pad.get("number", ""))
            is_ep = pad_num in ("0", "EP", "")

            # Thermal pad: explicitly named EP/0 with area > 4mm²,
            # or any pad with area > 9mm² (large enough to need thermal vias)
            if not ((is_ep and area > 4.0) or area > 9.0):
                continue

            # Must be at least 2x the average pad area (thermal pads are
            # distinctly larger than signal pads on the same component)
            if avg_pad_area > 0 and area < avg_pad_area * 2.0:
                continue

            # Must be on a ground or power net (thermal pads dissipate heat)
            pad_net_name = pad.get("net_name", "")
            net_upper = pad_net_name.upper()
            is_power_or_gnd = (
                net_upper in ("GND", "VSS", "AGND", "DGND", "PGND", "VCC", "VDD",
                              "AVCC", "AVDD", "DVCC", "DVDD", "VBUS")
                or net_upper.startswith("+")
                or net_upper.startswith("V+")
                or "GND" in net_upper
                or "VCC" in net_upper
                or "VDD" in net_upper
            )
            if not is_power_or_gnd and not is_ep:
                continue

            thermal_pads_found.append((pad, area))

        if not thermal_pads_found:
            continue

        for pad, pad_area in thermal_pads_found:
            pad_num = str(pad.get("number", ""))
            w = pad.get("width", 0)
            h = pad.get("height", 0)
            ax = pad.get("abs_x", fp["x"])
            ay = pad.get("abs_y", fp["y"])
            net_num = pad.get("net_number", -1)

            # Count vias within the thermal pad area
            # Account for footprint + pad rotation: the pad's width/height are
            # in the footprint's local coordinate frame, but the via positions
            # are in board space.  Rotate the via-to-pad offset back into the
            # pad's local frame for the rectangular containment check.
            fp_angle = fp.get("angle", 0)
            pad_angle = pad.get("angle", 0)
            total_angle = fp_angle + pad_angle
            total_rad = math.radians(-total_angle) if total_angle != 0 else 0.0
            cos_a = math.cos(total_rad) if total_angle != 0 else 1.0
            sin_a = math.sin(total_rad) if total_angle != 0 else 0.0

            half_w = w / 2.0
            half_h = h / 2.0
            vias_in_pad = 0
            vias_tented = 0
            vias_untented = 0

            for via in all_vias:
                vx, vy = via["x"], via["y"]
                # Transform via position into pad-local coordinates
                dx, dy = vx - ax, vy - ay
                if total_angle != 0:
                    dx, dy = dx * cos_a - dy * sin_a, dx * sin_a + dy * cos_a
                # Check if via is within the pad area (with small margin)
                if (abs(dx) <= half_w * 1.1 and
                        abs(dy) <= half_h * 1.1):
                    vias_in_pad += 1
                    # Check tenting
                    tenting = via.get("tenting", [])
                    if len(tenting) > 0:
                        vias_tented += 1
                    else:
                        vias_untented += 1

            # Count thru_hole pads in the same footprint on the same net
            # — these are footprint-embedded thermal vias (common in
            # QFN/BGA footprints like ESP32-S3-WROOM-1)
            footprint_via_pads = 0
            for other_pad in pads:
                if other_pad is pad:
                    continue
                if (other_pad.get("type") == "thru_hole" and
                        other_pad.get("net_number", -2) == net_num and
                        net_num >= 0):
                    footprint_via_pads += 1

            total_thermal_vias = vias_in_pad + footprint_via_pads

            # Compute density using total thermal vias
            density = 0.0
            if pad_area > 0:
                density = total_thermal_vias / pad_area

            # Recommendations based on pad area
            # Rule of thumb: ~1 via per 1-2mm² of thermal pad area
            # Small QFN (pad < 10mm²): minimum 5-9 vias
            # Medium QFN (10-25mm²): minimum 9-16 vias
            # Large QFN/BGA (>25mm²): scale by area
            if pad_area < 10:
                recommended_min = 5
                recommended_ideal = 9
            elif pad_area < 25:
                recommended_min = 9
                recommended_ideal = 16
            else:
                recommended_min = max(9, int(pad_area * 0.5))
                recommended_ideal = max(16, int(pad_area * 0.8))

            # Assess adequacy using total (standalone + footprint-embedded)
            if total_thermal_vias >= recommended_ideal:
                adequacy = "good"
            elif total_thermal_vias >= recommended_min:
                adequacy = "adequate"
            elif total_thermal_vias > 0:
                adequacy = "insufficient"
            else:
                adequacy = "none"

            entry: dict = {
                "component": ref,
                "value": fp.get("value", ""),
                "library": fp.get("library", ""),
                "layer": fp.get("layer", "F.Cu"),
                "pad_number": pad_num,
                "pad_size_mm": [round(w, 2), round(h, 2)],
                "pad_area_mm2": round(pad_area, 2),
                "net": pad.get("net_name", ""),
                "via_count": total_thermal_vias,
                "standalone_vias": vias_in_pad,
                "footprint_via_pads": footprint_via_pads,
                "via_density_per_mm2": round(density, 3),
                "vias_tented": vias_tented,
                "vias_untented": vias_untented,
                "recommended_min_vias": recommended_min,
                "recommended_ideal_vias": recommended_ideal,
                "adequacy": adequacy,
            }

            if vias_untented > 0:
                entry["tenting_note"] = (
                    f"{vias_untented} via(s) are not tented — solder may wick "
                    f"through during reflow, creating voids under the thermal pad"
                )

            results.append(entry)

    # Sort: worst adequacy first
    adequacy_order = {"none": 0, "insufficient": 1, "adequate": 2, "good": 3}
    results.sort(key=lambda r: (adequacy_order.get(r["adequacy"], 4),
                                r["component"]))
    return results


def analyze_copper_presence(footprints: list[dict], zones: list[dict],
                            zone_fills: ZoneFills) -> dict:
    """Check zone copper presence at component pad locations.

    Uses point-in-polygon tests against zone filled polygon data to determine
    actual copper presence. Rather than listing every component with the common
    pattern (e.g., GND pour under everything on a 2-layer board), this reports
    a compact summary plus detailed exceptions:

    - Summary: how many components have opposite-layer copper, grouped by net
    - Exceptions: components WITHOUT opposite-layer copper when most others
      have it (e.g., touch pads with clearance in the ground pour)
    - Foreign zones: components with same-layer copper from a zone they're not
      connected to

    Requires filled zone data — run Fill All Zones in KiCad before analysis.
    """
    if not zone_fills.has_data:
        return {
            "warning": "No filled polygon data — zones may not have been "
                       "filled. Run Edit → Fill All Zones (B) in KiCad and "
                       "re-save before analysis.",
        }

    # Classify every component by opposite-layer copper status.
    # Use the component center (first pad centroid) for the check.
    opp_covered: dict[str, set[str]] = {}  # ref -> set of opp zone net names
    opp_uncovered: list[str] = []  # refs with NO opposite-layer copper
    foreign_zone_details: list[dict] = []  # same-layer foreign zone hits

    for fp in footprints:
        ref = fp.get("reference", "")
        fp_layer = fp.get("layer", "F.Cu")
        opposite_layer = "B.Cu" if fp_layer == "F.Cu" else "F.Cu"
        pads = fp.get("pads", [])
        if not pads:
            continue

        # Check opposite-layer copper at each pad location
        has_opp = False
        opp_nets: set[str] = set()
        foreign_pads: list[dict] = []

        for pad in pads:
            px = pad.get("abs_x", fp["x"])
            py = pad.get("abs_y", fp["y"])
            pad_net = pad.get("net_number", 0)

            opp_zones = zone_fills.zones_at_point(
                px, py, opposite_layer, zones)
            if opp_zones:
                has_opp = True
                for z in opp_zones:
                    nn = z.get("net_name", "")
                    if nn:
                        opp_nets.add(nn)

            # Same-layer foreign zone check
            same_other = [
                z for z in zone_fills.zones_at_point(px, py, fp_layer, zones)
                if z.get("net", 0) != pad_net and pad_net > 0
            ]
            if same_other:
                foreign_pads.append({
                    "pad": str(pad.get("number", "")),
                    "position": [round(px, 3), round(py, 3)],
                    "foreign_zones": [z["net_name"] for z in same_other],
                })

        if has_opp:
            opp_covered[ref] = opp_nets
        else:
            opp_uncovered.append(ref)

        if foreign_pads:
            foreign_zone_details.append({
                "component": ref,
                "value": fp.get("value", ""),
                "layer": fp_layer,
                "pads": foreign_pads,
            })

    # Build compact summary
    # Group covered components by which nets they sit over
    net_groups: dict[str, list[str]] = {}  # "GND" -> [ref1, ref2, ...]
    for ref, nets in opp_covered.items():
        key = ", ".join(sorted(nets))
        net_groups.setdefault(key, []).append(ref)

    opp_summary: list[dict] = []
    for nets_str, refs in sorted(net_groups.items(),
                                 key=lambda x: -len(x[1])):
        opp_summary.append({
            "opposite_layer_nets": nets_str,
            "component_count": len(refs),
            "components": sorted(refs),
        })

    result: dict = {
        "opposite_layer_summary": opp_summary,
    }

    # The interesting signal: components WITHOUT opposite-layer copper
    if opp_uncovered:
        result["no_opposite_layer_copper"] = sorted(opp_uncovered)

    if foreign_zone_details:
        result["same_layer_foreign_zones"] = foreign_zone_details

    return result


def analyze_pcb(path: str, *, proximity: bool = False) -> dict:
    """Main analysis function.

    Args:
        path: Path to .kicad_pcb file.
        proximity: If True, run trace proximity analysis (spatial grid scan
            for signal nets running close together — useful for crosstalk
            assessment but adds computation time).
    """
    root = parse_file(path)

    layers = extract_layers(root)
    setup = extract_setup(root)
    net_names = extract_nets(root)
    footprints = extract_footprints(root)
    tracks = extract_tracks(root)
    vias = extract_vias(root)
    zones, zone_fills = extract_zones(root)
    outline = extract_board_outline(root)

    # Connectivity analysis (zone-aware)
    connectivity = analyze_connectivity(footprints, tracks, vias, net_names, zones)

    stats = compute_statistics(footprints, tracks, vias, zones, outline, connectivity, net_names)

    version = get_value(root, "version") or "unknown"
    generator_version = get_value(root, "generator_version") or "unknown"

    # Component grouping by reference prefix
    component_groups = group_components(footprints)

    # Per-net trace length measurement
    net_lengths = analyze_net_lengths(tracks, vias, net_names)

    # Power net routing analysis
    power_routing = analyze_power_nets(footprints, tracks, net_names)

    # Decoupling placement analysis
    decoupling = analyze_decoupling_placement(footprints)

    # Ground domain identification
    ground_domains = analyze_ground_domains(footprints, net_names, zones)

    # Current capacity facts
    current_capacity = analyze_current_capacity(tracks, vias, zones, net_names, setup)

    # Via analysis (types, annular ring, via-in-pad, fanout, current)
    via_analysis = analyze_vias(vias, footprints, net_names)

    # Thermal / via stitching analysis
    thermal = analyze_thermal_vias(footprints, vias, zones)

    # Layer transitions for ground return path analysis
    layer_transitions = analyze_layer_transitions(tracks, vias, net_names)

    # Placement analysis (courtyard overlaps, edge clearance, density)
    placement = analyze_placement(footprints, outline)

    # Silkscreen text extraction
    silkscreen = extract_silkscreen(root, footprints)

    # Board metadata (title block, properties, paper size)
    metadata = extract_board_metadata(root)

    # Dimension annotations
    dimensions = extract_dimensions(root)

    # Groups (designer-defined component/routing groupings)
    groups = extract_groups(root)

    # Net classes (KiCad 5 legacy — stored in PCB file)
    net_classes = extract_net_classes(root)

    # DFM (Design for Manufacturing) scoring
    dfm = analyze_dfm(footprints, tracks, vias, outline,
                       setup.get("design_rules"))

    # Tombstoning risk assessment for small passives
    tombstoning = analyze_tombstoning_risk(footprints, tracks, vias, zones)

    # Thermal pad via adequacy for QFN/BGA packages
    thermal_pad_vias = analyze_thermal_pad_vias(footprints, vias)

    # Copper presence analysis (cross-layer zone fill at pad locations)
    copper_presence = analyze_copper_presence(footprints, zones, zone_fills)

    # Compact footprint output (exclude raw pad data for summary, keep it in full output)
    footprint_summary = []
    for fp in footprints:
        fp_summary = {k: v for k, v in fp.items() if k != "pads"}
        # Add net summary per footprint
        fp_nets = set()
        for pad in fp["pads"]:
            nn = pad.get("net_name", "")
            if nn:
                fp_nets.add(nn)
        fp_summary["connected_nets"] = sorted(fp_nets)
        footprint_summary.append(fp_summary)

    result = {
        "file": str(path),
        "kicad_version": generator_version,
        "file_version": version,
        "statistics": stats,
        "layers": layers,
        "setup": setup,
        "nets": {v: k for k, v in net_names.items() if v},  # net_name -> net_index
        "board_outline": outline,
        "component_groups": component_groups,
        "footprints": footprint_summary,
        "tracks": {
            "segment_count": tracks["segment_count"],
            "arc_count": tracks["arc_count"],
            "width_distribution": tracks["width_distribution"],
            "layer_distribution": tracks["layer_distribution"],
            # Omit individual segments — too large. Use --full for that.
        },
        "vias": {
            "count": vias["count"],
            "size_distribution": vias["size_distribution"],
            **({"via_analysis": via_analysis} if via_analysis else {}),
        },
        "zones": zones,
        "connectivity": connectivity,
        "net_lengths": net_lengths,
    }

    if power_routing:
        result["power_net_routing"] = power_routing
    if decoupling:
        result["decoupling_placement"] = decoupling
    if ground_domains["domain_count"] > 0:
        result["ground_domains"] = ground_domains
    if current_capacity["power_ground_nets"] or current_capacity["narrow_signal_nets"]:
        result["current_capacity"] = current_capacity
    if thermal["zone_stitching"] or thermal["thermal_pads"]:
        result["thermal_analysis"] = thermal
    if layer_transitions:
        result["layer_transitions"] = layer_transitions
    if placement.get("courtyard_overlaps") or placement.get("edge_clearance_warnings"):
        result["placement_analysis"] = placement
    elif placement.get("density"):
        result["placement_analysis"] = {"density": placement["density"]}
    result["silkscreen"] = silkscreen
    if proximity:
        result["trace_proximity"] = analyze_trace_proximity(tracks, net_names)

    # New extraction sections — always include if non-empty
    if metadata:
        result["board_metadata"] = metadata
    if dimensions:
        result["dimensions"] = dimensions
    if groups:
        result["groups"] = groups
    if net_classes:
        result["net_classes"] = net_classes

    # Manufacturing and assembly analysis
    if dfm:
        result["dfm"] = dfm
    if tombstoning:
        result["tombstoning_risk"] = tombstoning
    if thermal_pad_vias:
        result["thermal_pad_vias"] = thermal_pad_vias
    if copper_presence:
        result["copper_presence"] = copper_presence

    return result


def main():
    import argparse
    parser = argparse.ArgumentParser(description="KiCad PCB Layout Analyzer")
    parser.add_argument("pcb", help="Path to .kicad_pcb file")
    parser.add_argument("--output", "-o", help="Output JSON file (default: stdout)")
    parser.add_argument("--compact", action="store_true", help="Compact JSON output")
    parser.add_argument("--full", action="store_true",
                        help="Include individual track/via coordinate data")
    parser.add_argument("--proximity", action="store_true",
                        help="Run trace proximity analysis for crosstalk assessment")
    args = parser.parse_args()

    result = analyze_pcb(args.pcb, proximity=args.proximity)

    if args.full:
        # Re-parse to get full track/via data
        root = parse_file(args.pcb)
        track_data = extract_tracks(root)
        result["tracks"]["segments"] = track_data["segments"]
        result["tracks"]["arcs"] = track_data["arcs"]
        result["vias"]["vias"] = extract_vias(root)["vias"]

    indent = None if args.compact else 2
    output = json.dumps(result, indent=indent, default=str)

    if args.output:
        Path(args.output).write_text(output)
        print(f"Written to {args.output}", file=sys.stderr)
    else:
        print(output)


if __name__ == "__main__":
    main()
