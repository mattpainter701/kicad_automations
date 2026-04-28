"""Top-level generator — BOM → .kicad_sch files.

Orchestrates: component lookup → sheet allocation → auto-placement → schematic output.

Usage:
    from schematic_engine.generator import generate_from_bom
    generate_from_bom("my_bom.csv", output_dir="output/", project_name="MyBoard")

Or from CLI:
    python -m schematic_engine.generator my_bom.csv --output output/ --project MyBoard
"""

import copy
import logging
import math
import os
import re
import sys
import zlib
from pathlib import Path

from .allocator import allocate_sheets
from .component_db import (
    BUILTIN_REGISTRY,
    ComponentDef,
    ComponentRegistry,
    PresentationWiringPolicy,
    auto_generate_bypass_caps,
    component_explanation_lines,
    infer_passive_component,
    normalize_presentation_wiring_policy,
    parse_bom_csv,
)
from .placer import (
    SheetLayout,
    component_annotation_start_y,
    component_body_bounds,
    layout_sheet,
    reset_ref_counters,
)
from .primitives import (
    PAPER_SIZES,
    TITLE_BLOCK_H,
    assemble_sheet,
    center_content,
    configure_deterministic_uids,
    connect_pin_to_hierarchical_label,
    connect_pin_to_label,
    connect_points,
    create_generic_symbol,
    disable_deterministic_uids,
    estimate_content_bounds,
    get_pin_positions,
    passive_pin_angles,
    passive_pin_xy,
    pin_connection_point,
    place_component,
    sexpr_header,
    sexpr_no_connect,
    sexpr_pwr_flag_instance,
    sexpr_pwr_flag_lib_entry,
    sexpr_sheet_pin,
    sexpr_wire,
    sheet_title_text,
    snap,
    text_annotation,
    uid,
)
from .sexpr_builder import (
    adjust_symbol_y_coordinates as _adjust_symbol_y_coordinates,
)
from .sexpr_builder import (
    clean_symbol_properties as _clean_symbol_properties,
)
from .sexpr_builder import (
    normalize_symbol_all_coordinates as _normalize_symbol_all_coordinates,
)
from .sexpr_builder import (
    normalize_symbol_property_x as _normalize_symbol_property_x,
)
from .sexpr_builder import (
    validate_sexpr_balance as _validate_sexpr_balance,
)
from .validator import run_validation_checks

_logger = logging.getLogger(__name__)

_UUID_ENV_VARS = ("SCHEMATIC_ENGINE_STABLE_UUIDS", "SCHEMATIC_ENGINE_DETERMINISTIC_UUIDS")
_INTERFACE_POLICIES = {"inferred", "explicit"}
_PAPER_ORDER = ("A4", "A3", "A2", "A1", "A0")
_RENDER_FIT_MARGIN = 10.0
_TITLE_BLOCK_COMMENT2_LIMIT = 84
_TITLE_BLOCK_COMMENT3_LIMIT = 56

# Power net prefixes — KiCad convention keeps power as global_label even in
# hierarchical designs, so they are excluded from hierarchical promotion.
_POWER_NET_PREFIXES = ("VDD", "VCC", "VBUS", "VIN", "VDDA", "MGT", "VCCO")
_LOCAL_ROUTE_CLEARANCE = snap(2.54)
_LOCAL_ROUTE_LANE_PITCH = snap(3.81)
_LOCAL_ROUTE_LANE_BASE = snap(3.81)
# T198 — Cap lane index so dense connectors don't drift wires unboundedly.
# At index 6, the lane sits ~26.7mm from the obstacle face, which is the
# practical readability ceiling. Beyond that, lanes wrap (and routing falls
# back to the box-bypass detours in `_route_local_connection`).
_LANE_INDEX_MAX = 6

# Pin names that are safe to no-connect without warning.
_NC_PIN_NAME_PATTERNS = re.compile(r"^(~|NC|DNC|N\.?C\.?|NO.?CONNECT|RESERVED)$", re.IGNORECASE)

# Pin electrical types that are safe to no-connect (output-like: unused outputs are fine).
_SAFE_NC_PIN_TYPES = frozenset(
    {
        "output",
        "power_out",
        "open_collector",
        "open_emitter",
        "no_connect",
        "free",
    }
)

# Pin types that MUST be connected — floating these is an error.
_CRITICAL_PIN_TYPES = frozenset({"power_in"})


def _classify_unhandled_pin(comp, pin_num, pname, ptype):
    """Classify an unhandled pin and return (action, level, reason).

    action: "no_connect" | "no_connect"  (always NC in schematic, but level differs)
    level:  "silent" | "warning" | "error"
    reason: human-readable explanation
    """
    # 1. Explicitly marked as intentional NC by the template/component author
    if pin_num in comp.explicit_no_connects:
        return "no_connect", "silent", "explicit no-connect (by design)"

    # 2. Pin name indicates NC
    if _NC_PIN_NAME_PATTERNS.match(pname):
        return "no_connect", "silent", f"pin name '{pname}' indicates no-connect"

    # 3. Build a pin type lookup from ComponentDef.pins for richer type info
    comp_pin_type = None
    for pin in comp.pins:
        if pin.number == pin_num:
            comp_pin_type = pin.electrical_type
            break

    # Use ComponentDef pin type if available, fall back to symbol ptype
    etype = comp_pin_type or ptype or "unspecified"

    # 4. Critical pins — should never be left floating
    if etype in _CRITICAL_PIN_TYPES:
        return (
            "no_connect",
            "error",
            f"FLOATING {etype} pin '{pname}' (pin {pin_num}) — must be connected to a rail",
        )

    # 5. Safe output-like pins
    if etype in _SAFE_NC_PIN_TYPES:
        return "no_connect", "silent", f"unused {etype} pin"

    # 6. Input / bidirectional / passive — likely needs a connection
    if etype in ("input", "bidirectional", "tri_state"):
        return (
            "no_connect",
            "warning",
            f"unconnected {etype} pin '{pname}' (pin {pin_num}) — may need pull-up/down or driver",
        )

    # 7. Passive pins — context-dependent, warn mildly
    if etype == "passive":
        return (
            "no_connect",
            "warning",
            f"unconnected passive pin '{pname}' (pin {pin_num}) — verify intent",
        )

    # 8. Unspecified / unknown — warn
    return (
        "no_connect",
        "warning",
        f"unconnected pin '{pname}' (pin {pin_num}, type={etype}) — verify intent",
    )


_DENSE_FACE_KEEP_OUT = snap(2.54)
_DENSE_FACE_STAGGER_STEP = snap(2.54)
_STRAP_ENDPOINT_STUB_LEN = snap(3.81)


def _is_power_net(name: str) -> bool:
    """Return True if *name* is a power/ground net that should remain global."""
    return name == "GND" or name.startswith(_POWER_NET_PREFIXES)


def _normalize_interface_policy(interface_policy: str | None) -> str:
    """Return a validated hierarchical interface policy."""
    if interface_policy is None:
        return "inferred"
    normalized = interface_policy.strip().lower()
    if normalized not in _INTERFACE_POLICIES:
        valid = ", ".join(sorted(_INTERFACE_POLICIES))
        raise ValueError(f"Unknown interface policy '{interface_policy}'. Expected one of: {valid}")
    return normalized


def _stable_sort_index(name: str) -> int:
    """Deterministic integer for sorting unmatched nets across regenerations."""
    return zlib.crc32((name or "").encode("utf-8")) & 0x7FFFFFFF


def classify_net_group(net_name: str) -> tuple[str, int]:
    """Classify a signal net into a group and sort index for pin ordering.

    Returns (group_name, sort_index) where group_name groups related signals
    and sort_index orders within the group. Example:
    - "DDR_DQ0" → ("DDR_DATA", 0)
    - "DDR_DQ15" → ("DDR_DATA", 15)
    - "ADRV_SPI_CLK" → ("ADRV_SPI", 0)
    - "ADRV_SPI_MOSI" → ("ADRV_SPI", 2)

    Differential pairs are placed adjacent by shared basename: *_P sorts
    immediately before *_N within the same pair group.
    """
    # DDR memory interface
    m = re.match(r"DDR_DQ(\d+)$", net_name)
    if m:
        return ("DDR_DATA", int(m.group(1)))

    m = re.match(r"DDR_A(\d+)$", net_name)
    if m:
        return ("DDR_ADDR", int(m.group(1)))

    m = re.match(r"DDR_DQS(\d+)_([PN])$", net_name)
    if m:
        idx = int(m.group(1)) * 2 + (0 if m.group(2) == "P" else 1)
        return ("DDR_DQS", idx)

    m = re.match(r"DDR_DM(\d+)$", net_name)
    if m:
        return ("DDR_DM", int(m.group(1)))

    # Ethernet
    m = re.match(r"ETH_RXD(\d+)$", net_name)
    if m:
        return ("ETH_RX", int(m.group(1)))

    m = re.match(r"ETH_TXD(\d+)$", net_name)
    if m:
        return ("ETH_TX", int(m.group(1)))

    m = re.match(r"ETH_(\w+)", net_name)
    if m:
        return ("ETH_CTRL", 0)

    # ADRV9006 transceiver
    m = re.match(r"ADRV_AGPIO(\d+)$", net_name)
    if m:
        return ("ADRV_AGPIO", int(m.group(1)))

    m = re.match(r"ADRV_DGPIO(\d+)$", net_name)
    if m:
        return ("ADRV_DGPIO", int(m.group(1)))

    m = re.match(r"ADRV_SPI_(\w+)$", net_name)
    if m:
        signal = m.group(1)
        spi_order = {"CLK": 0, "CSN": 1, "MOSI": 2, "MISO": 3}
        return ("ADRV_SPI", spi_order.get(signal, 4))

    # Clock tree
    m = re.match(r"CLK_SPI_(\w+)$", net_name)
    if m:
        return ("CLK_SPI", 0)

    # General purpose I/O
    m = re.match(r"PMOD_IO(\d+)$", net_name)
    if m:
        return ("PMOD", int(m.group(1)))

    # Zynq BANK pins (PL_IO_L25N_P_13_1 → bank 13, pin L25)
    m = re.match(r"PL_IO_L(\d+)([PN])_.*_(\d+)$", net_name)
    if m:
        bank = int(m.group(3))
        line = int(m.group(1))
        pn = 0 if m.group(2) == "P" else 1
        # Sort by bank, then by line pair, then by P/N
        sort_idx = bank * 10000 + line * 2 + pn
        return ("PL_BANK", sort_idx)

    # Serial interfaces
    m = re.match(r"UART(\d+)_(\w+)$", net_name)
    if m:
        return ("UART", int(m.group(1)))

    # Storage interfaces
    m = re.match(r"SD_(.+)$", net_name)
    if m:
        return ("SD", 0)

    m = re.match(r"QSPI_(.+)$", net_name)
    if m:
        return ("QSPI", 0)

    # Differential pairs (generic fallback) — group by shared basename so
    # CLK1_P/CLK1_N stay adjacent instead of all _P and _N signals clustering.
    if net_name.endswith("_P"):
        base = net_name[:-2]
        return (f"__DIFF:{base}", 0)

    if net_name.endswith("_N"):
        base = net_name[:-2]
        return (f"__DIFF:{base}", 1)

    # Unknown/miscellaneous nets
    return ("_misc", _stable_sort_index(net_name))


def _component_pin_sort_key(comp: ComponentDef):
    """Return a sort key builder that prefers resolved board nets over pin names."""

    def _sort_key(pin_tuple) -> tuple[str, int]:
        pin_num, pin_name, _ptype, _side = pin_tuple
        net_name = comp.pin_nets.get(pin_num) or comp.power_pins.get(pin_num) or pin_name
        return classify_net_group(net_name)

    return _sort_key


_FEATURE_HINTS = (
    (("fpga", "kintex", "zynq", "artix", "spartan"), "FPGA"),
    (("arm", "cortex"), "ARM"),
    (("ddr3", "ddr3l"), "DDR3"),
    (("ddr4", "ddr4l"), "DDR4"),
    (("qspi", "spi flash", "nor flash"), "QSPI"),
    (("usb 3", "usb3", "superspeed"), "USB 3.0"),
    (("usb 2", "usb2", "hub"), "USB 2.0 Hub"),
    (("mux",), "Mux"),
    (("clock", "sysref"), "Clocking"),
    (("lvds",), "LVDS"),
    (("transceiver", "rf"), "RF"),
    (("ethernet", "rgmii", "gige", "gigabit"), "Ethernet"),
    (("poe",), "PoE"),
    (("gps", "gnss"), "GPS"),
    (("eeprom",), "EEPROM"),
    (("microsd", "sd card", "sdio"), "microSD"),
    (("sensor", "imu", "humidity", "pressure"), "Sensors"),
)


def _env_flag_enabled() -> bool:
    for env_var in _UUID_ENV_VARS:
        value = os.getenv(env_var, "")
        if value.lower() in {"1", "true", "yes", "on"}:
            return True
    return False


def _shorten(text: str, limit: int) -> str:
    text = " ".join((text or "").split())
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)].rstrip() + "..."


def _component_identity(comp: ComponentDef) -> str:
    source_ref = comp.source_ref or "-"
    source_mpn = comp.source_mpn or comp.mpn
    source_value = comp.source_value or comp.value
    return f"{source_ref}|{source_mpn}|{source_value}|{comp.category}"


def _apply_bom_overlay(comp: ComponentDef, row, copy_index: int) -> ComponentDef:
    """Attach BOM metadata to a copied component instance without mutating the registry."""
    instance = copy.deepcopy(comp)
    instance.source_ref = row.ref if copy_index == 0 else ""
    instance.source_mpn = row.mpn or comp.mpn
    instance.source_value = row.value or comp.value
    instance.source_description = row.description or comp.description
    instance.source_manufacturer = row.manufacturer
    if row.value:
        instance.value = row.value
    if row.description:
        instance.description = row.description
    return instance


def _dedupe_preserve_order(items):
    seen = set()
    result = []
    for item in items:
        if not item or item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


def _keyword_in_text(haystack: str, keyword: str) -> bool:
    pattern = rf"(?<![a-z0-9]){re.escape(keyword)}(?![a-z0-9])"
    return re.search(pattern, haystack) is not None


def _component_features(comp: ComponentDef) -> list[str]:
    features = list(comp.features)
    haystack = " ".join(
        part
        for part in (
            comp.source_description,
            comp.description,
            comp.source_value,
            comp.value,
            comp.category,
        )
        if part
    ).lower()
    for keywords, label in _FEATURE_HINTS:
        if any(_keyword_in_text(haystack, keyword) for keyword in keywords):
            features.append(label)
    return _dedupe_preserve_order(features)


def _render_symbol_name_and_sexpr(comp: ComponentDef) -> tuple[str, str]:
    if comp.lib_symbol_sexpr and not comp.prefer_multi_column_symbol():
        match = re.search(r'\(symbol\s+"([^"]+)"', comp.lib_symbol_sexpr)
        sym_name = match.group(1) if match else comp.mpn
        # Clean up the symbol to remove vendor-specific properties with bad coordinates
        cleaned_sexpr = _clean_symbol_properties(comp.lib_symbol_sexpr)
        # Normalize property X coordinates to 0 (library extraction corruption fix)
        normalized_sexpr = _normalize_symbol_property_x(cleaned_sexpr)
        # Normalize ALL coordinates to be centered at symbol origin (fixes absolute coords in polylines/pins)
        all_coords_normalized = _normalize_symbol_all_coordinates(normalized_sexpr)
        # Adjust Y coordinates to ensure all geometry has Y >= 0
        adjusted_sexpr = _adjust_symbol_y_coordinates(all_coords_normalized)
        return sym_name, adjusted_sexpr
    sym_name = comp.mpn.replace("-", "_").replace(".", "_")
    generated_sexpr = create_generic_symbol(
        sym_name,
        comp.pin_tuples(),
        comp.ref_prefix,
        column_segments=comp.preferred_symbol_column_segments(),
        pin_pitch_override=comp.preferred_symbol_pin_pitch_mm(),
        pin_sort_fn=_component_pin_sort_key(comp),
    )
    # Apply Y-coordinate adjustment as final safeguard (should be minimal for generated symbols)
    adjusted_sexpr = _adjust_symbol_y_coordinates(generated_sexpr)
    return sym_name, adjusted_sexpr


def _resolve_late_pin_maps(components: list[ComponentDef]) -> None:
    """Resolve deferred pin-map builders before validation/reporting.

    Some large imported/custom symbols populate ``pin_nets`` / ``power_pins``
    from symbol geometry via ``pin_map_builder``.  Doing this only during
    rendering makes validation and reports observe a different component state
    than the generator console.  Resolve them once up front so all downstream
    checks see the same connectivity.
    """
    for comp in components:
        if not comp.pin_map_builder or comp.pin_nets or comp.power_pins:
            continue
        sym_name, sym_sexpr = _render_symbol_name_and_sexpr(comp)
        pin_pos = get_pin_positions(sym_sexpr, sym_name)
        all_nets = comp.pin_map_builder(pin_pos)
        for pin_num, net in all_nets.items():
            if net in ("GND",) or net.startswith(("VDD", "VCC", "VBUS", "VDDA", "MGT")):
                comp.power_pins[pin_num] = net
            else:
                comp.pin_nets[pin_num] = net


def _expand_box(
    box: tuple[float, float, float, float], clearance: float = _LOCAL_ROUTE_CLEARANCE
) -> tuple[float, float, float, float]:
    left, top, right, bottom = box
    return (
        snap(left - clearance),
        snap(top - clearance),
        snap(right + clearance),
        snap(bottom + clearance),
    )


def _symbol_body_rects(symbol_sexpr: str) -> list[tuple[float, float, float, float]]:
    rects = []
    for x1, y1, x2, y2 in re.findall(
        r"\(rectangle\s+\(start\s+([-\d.]+)\s+([-\d.]+)\)\s+\(end\s+([-\d.]+)\s+([-\d.]+)\)",
        symbol_sexpr,
    ):
        left = min(float(x1), float(x2))
        right = max(float(x1), float(x2))
        bottom = min(float(y1), float(y2))
        top = max(float(y1), float(y2))
        rects.append((left, right, bottom, top))
    return rects


def _safe_label_stub_length(
    pin_x: float,
    pin_y: float,
    pin_angle: int,
    body_rects: list[tuple[float, float, float, float]],
    default_len: float = 7.62,
) -> float:
    """Shorten pin stubs when a neighboring symbol column would be crossed."""
    if not body_rects:
        return default_len

    if pin_angle == 0:
        gaps = [pin_x - right for left, right, bottom, top in body_rects if bottom <= pin_y <= top and right <= pin_x]
    elif pin_angle == 180:
        gaps = [left - pin_x for left, right, bottom, top in body_rects if bottom <= pin_y <= top and left >= pin_x]
    elif pin_angle == 270:
        gaps = [pin_y - top for left, right, bottom, top in body_rects if left <= pin_x <= right and top <= pin_y]
    elif pin_angle == 90:
        gaps = [bottom - pin_y for left, right, bottom, top in body_rects if left <= pin_x <= right and bottom >= pin_y]
    else:
        gaps = []

    positive_gaps = [gap for gap in gaps if gap > 0.05]
    if not positive_gaps:
        return default_len
    return snap(max(1.27, min(default_len, min(positive_gaps))))


def _dense_pin_stub_lengths(
    comp: ComponentDef,
    pin_pos: dict[str, tuple[float, float, int, float, str, str]],
    body_rects: list[tuple[float, float, float, float]],
) -> dict[str, float]:
    """Return per-pin stub lengths with extra spacing on dense symbol faces."""
    overrides: dict[str, float] = {}
    netted_pins = set(comp.pin_nets) | set(comp.power_pins)
    by_side: dict[str, list[tuple[float, str, float, float, int]]] = {}

    for pin_num in netted_pins:
        if pin_num not in pin_pos:
            continue
        px, py, pangle, _plen, _pname, _ptype = pin_pos[pin_num]
        side = _get_pin_side(pangle)
        axis = py if side in ("left", "right") else px
        by_side.setdefault(side, []).append((axis, pin_num, px, py, pangle))

    for side, items in by_side.items():
        items.sort(key=lambda item: item[0])
        gaps = [abs(items[i + 1][0] - items[i][0]) for i in range(len(items) - 1)]
        dense = len(items) >= 10 or (gaps and min(gaps) <= snap(2.54) + 0.01)
        ladder_depth = 1
        if dense:
            ladder_depth = 4 if len(items) >= 24 else 3 if len(items) >= 12 else 2

        for idx, (_axis, pin_num, px, py, pangle) in enumerate(items):
            base = _safe_label_stub_length(px, py, pangle, body_rects)
            keepout = _DENSE_FACE_KEEP_OUT if dense else snap(1.27)
            ladder = (idx % ladder_depth) * _DENSE_FACE_STAGGER_STEP if dense else 0.0
            overrides[pin_num] = snap(base + keepout + ladder)

    return overrides


def _segment_hits_box(x1: float, y1: float, x2: float, y2: float, box: tuple[float, float, float, float]) -> bool:
    """Return True when an orthogonal segment runs through a box interior."""
    eps = 0.01
    left, top, right, bottom = box
    if abs(x1 - x2) < eps:
        if not (left + eps < x1 < right - eps):
            return False
        seg_top, seg_bottom = sorted((y1, y2))
        return max(seg_top, top + eps) < min(seg_bottom, bottom - eps)
    if abs(y1 - y2) < eps:
        if not (top + eps < y1 < bottom - eps):
            return False
        seg_left, seg_right = sorted((x1, x2))
        return max(seg_left, left + eps) < min(seg_right, right - eps)
    return False


def _polyline_is_clear(points: list[tuple[float, float]], box: tuple[float, float, float, float] | None) -> bool:
    if box is None:
        return True
    for (x1, y1), (x2, y2) in zip(points, points[1:]):
        if _segment_hits_box(x1, y1, x2, y2, box):
            return False
    return True


def _polyline_length(points: list[tuple[float, float]]) -> float:
    return sum(abs(x2 - x1) + abs(y2 - y1) for (x1, y1), (x2, y2) in zip(points, points[1:]))


def _normalize_polyline(points: list[tuple[float, float]]) -> list[tuple[float, float]]:
    normalized = []
    for x, y in points:
        pt = (snap(x), snap(y))
        if normalized and abs(normalized[-1][0] - pt[0]) < 0.01 and abs(normalized[-1][1] - pt[1]) < 0.01:
            continue
        normalized.append(pt)
    return normalized


def _emit_polyline(points: list[tuple[float, float]], wires: list[str]) -> None:
    for (x1, y1), (x2, y2) in zip(points, points[1:]):
        if abs(x1 - x2) < 0.01 and abs(y1 - y2) < 0.01:
            continue
        wires.append(sexpr_wire(x1, y1, x2, y2))


def _point_box_side(point: tuple[float, float], box: tuple[float, float, float, float]) -> str:
    """Return the nearest obstacle side for a point outside or on the obstacle bounds."""
    x, y = point
    left, top, right, bottom = box
    if x <= left:
        return "left"
    if x >= right:
        return "right"
    if y <= top:
        return "top"
    if y >= bottom:
        return "bottom"

    distances = {
        "left": abs(x - left),
        "right": abs(x - right),
        "top": abs(y - top),
        "bottom": abs(y - bottom),
    }
    return min(distances, key=distances.get)


def _lane_bucket_value(point: tuple[float, float], side: str) -> int:
    axis_value = point[1] if side in ("left", "right") else point[0]
    return int(round(axis_value / _LOCAL_ROUTE_LANE_PITCH))


def _reserve_lane(route_state: dict[str, dict], side: str, point: tuple[float, float]) -> int:
    """Reserve or reuse a routing lane index for a side/position bucket.

    Lane indices are capped at ``_LANE_INDEX_MAX`` and wrap with modulo so
    that a sheet with 50 connections from the same IC face does not drift
    the 50th lane to ~194mm away. Wrapping reuses inner lanes; conflicts
    among same-bucket connections are resolved by the box-bypass detours
    in `_route_local_connection`. (T198)
    """
    lane_cache = route_state.setdefault("lane_cache", {})
    lane_next = route_state.setdefault("lane_next", {"left": 0, "right": 0, "top": 0, "bottom": 0})
    bucket_key = (side, _lane_bucket_value(point, side))
    if bucket_key not in lane_cache:
        lane_cache[bucket_key] = lane_next[side] % (_LANE_INDEX_MAX + 1)
        lane_next[side] += 1
    return lane_cache[bucket_key]


def _lane_axis_value(box: tuple[float, float, float, float], side: str, lane_index: int) -> float:
    left, top, right, bottom = box
    offset = _LOCAL_ROUTE_LANE_BASE + lane_index * _LOCAL_ROUTE_LANE_PITCH
    if side == "left":
        return snap(left - offset)
    if side == "right":
        return snap(right + offset)
    if side == "top":
        return snap(top - offset)
    return snap(bottom + offset)


def _lane_escape_point(point: tuple[float, float], side: str, lane_axis: float) -> tuple[float, float]:
    x, y = point
    if side in ("left", "right"):
        return (snap(lane_axis), snap(y))
    return (snap(x), snap(lane_axis))


def _lane_route_candidates(
    start: tuple[float, float],
    end: tuple[float, float],
    box: tuple[float, float, float, float],
    route_state: dict[str, dict],
) -> list[list[tuple[float, float]]]:
    """Return side-lane routing candidates around an obstacle."""
    start_side = _point_box_side(start, box)
    end_side = _point_box_side(end, box)
    start_lane = _lane_axis_value(box, start_side, _reserve_lane(route_state, start_side, start))
    end_lane = _lane_axis_value(box, end_side, _reserve_lane(route_state, end_side, end))
    start_escape = _lane_escape_point(start, start_side, start_lane)
    end_escape = _lane_escape_point(end, end_side, end_lane)

    candidates = []
    if abs(start_escape[0] - end_escape[0]) < 0.01 or abs(start_escape[1] - end_escape[1]) < 0.01:
        candidates.append([start, start_escape, end_escape, end])
    else:
        candidates.append([start, start_escape, (end_escape[0], start_escape[1]), end_escape, end])
        candidates.append([start, start_escape, (start_escape[0], end_escape[1]), end_escape, end])

    # Same-side routes benefit from a shared outer lane instead of collapsing back inward.
    if start_side == end_side:
        shared_lane = _lane_axis_value(
            box,
            start_side,
            max(
                _reserve_lane(route_state, start_side, start),
                _reserve_lane(route_state, end_side, end),
            ),
        )
        shared_start = _lane_escape_point(start, start_side, shared_lane)
        shared_end = _lane_escape_point(end, end_side, shared_lane)
        if abs(shared_start[0] - shared_end[0]) < 0.01 or abs(shared_start[1] - shared_end[1]) < 0.01:
            candidates.append([start, shared_start, shared_end, end])
        else:
            candidates.append([start, shared_start, (shared_end[0], shared_start[1]), shared_end, end])

    return candidates


def _route_local_connection(
    x1: float,
    y1: float,
    x2: float,
    y2: float,
    wires: list[str],
    obstacle: tuple[float, float, float, float] | None = None,
    route_state: dict[str, dict] | None = None,
) -> None:
    """Route a local passive connection, detouring around the parent symbol body."""
    start = (snap(x1), snap(y1))
    end = (snap(x2), snap(y2))
    expanded_box = _expand_box(obstacle) if obstacle is not None else None

    def _pick_best(candidates: list[list[tuple[float, float]]]) -> list[tuple[float, float]] | None:
        valid = []
        for candidate in candidates:
            polyline = _normalize_polyline(candidate)
            if len(polyline) < 2:
                continue
            if _polyline_is_clear(polyline, expanded_box):
                valid.append(polyline)
        if not valid:
            return None
        return min(valid, key=lambda pts: (_polyline_length(pts), len(pts)))

    if expanded_box is not None and route_state is not None:
        lane_best = _pick_best(_lane_route_candidates(start, end, expanded_box, route_state))
        if lane_best is not None:
            _emit_polyline(lane_best, wires)
            return

    candidates = [
        [start, (end[0], start[1]), end],
        [start, (start[0], end[1]), end],
    ]

    if expanded_box is not None:
        left, top, right, bottom = expanded_box
        candidates.extend(
            [
                [start, (left, start[1]), (left, end[1]), end],
                [start, (right, start[1]), (right, end[1]), end],
                [start, (start[0], top), (end[0], top), end],
                [start, (start[0], bottom), (end[0], bottom), end],
            ]
        )

    best = _pick_best(candidates)
    if best is not None:
        _emit_polyline(best, wires)
        return

    connect_points(start[0], start[1], end[0], end[1], wires)


def _render_passive_net_endpoint(
    net_name: str,
    pin_x: float,
    pin_y: float,
    pin_angle: int,
    wires: list[str],
    labels: list[str],
    power_instances: list[str],
    power_lib_names: set[str],
    label_fn,
    project_name: str,
    root_uuid: str,
    sheet_uuid: str,
    wire_len: float = 1.27,
) -> None:
    """Render a passive pin endpoint symbolically via a short stub and net marker."""
    if _is_power_net(net_name):
        if pin_angle == 0:
            wx, wy = pin_x - wire_len, pin_y
        elif pin_angle == 180:
            wx, wy = pin_x + wire_len, pin_y
        elif pin_angle == 270:
            wx, wy = pin_x, pin_y - wire_len
        elif pin_angle == 90:
            wx, wy = pin_x, pin_y + wire_len
        else:
            wx, wy = pin_x - wire_len, pin_y
        wires.append(sexpr_wire(pin_x, pin_y, wx, wy))
        from .primitives import sexpr_power_instance

        power_instances.append(
            sexpr_power_instance(
                net_name,
                wx,
                wy,
                pin_angle,
                project_name=project_name,
                root_uuid=root_uuid,
                sheet_uuid=sheet_uuid,
            )
        )
        power_lib_names.add(net_name)
        return

    label_fn(net_name)(pin_x, pin_y, pin_angle, net_name, wires, labels, wire_len=wire_len)


def _nearest_local_anchor(layout: SheetLayout, net_name: str, x: float, y: float):
    """Return the closest local anchor for ``net_name`` on this sheet, if any."""
    candidates = [anchor for anchor in layout.local_net_anchors if anchor.name == net_name]
    if not candidates:
        return None
    return min(candidates, key=lambda anchor: (anchor.x - x) ** 2 + (anchor.y - y) ** 2)


def _topology_parent_pin_point(parent_pc, parent_pins: dict, pp, net_name: str):
    """Return the owning parent pin point for topology-local routing, if applicable."""
    if parent_pc is None or not pp.owner_pin:
        return None
    owner_net = parent_pc.comp.pin_nets.get(pp.owner_pin) or parent_pc.comp.power_pins.get(pp.owner_pin)
    if owner_net != net_name:
        return None
    points = parent_pins.get(net_name, [])
    if not points:
        return None
    return points[0]


def _sheet_comment2(layout: SheetLayout) -> str:
    entries = []
    for placed in layout.placed_ics[:3]:
        comp = placed.comp
        mpn = comp.source_mpn or comp.mpn
        desc = comp.source_description or comp.description
        entry = f"{placed.ref} {mpn}"
        if desc:
            # Remove parentheses from description to avoid unbalanced brackets after double-escaping
            safe_desc = desc.replace("(", "").replace(")", "")
            entry += f" [{_shorten(safe_desc, 30)}]"
        entries.append(entry)
    remaining = len(layout.placed_ics) - len(entries)
    if remaining > 0:
        entries.append(f"+{remaining} more")
    summary = "; ".join(entries) if entries else f"{len(layout.placed_ics)} components"
    return _shorten(summary, _TITLE_BLOCK_COMMENT2_LIMIT)


def _sheet_comment3(layout: SheetLayout) -> str:
    features = []
    for placed in layout.placed_ics:
        features.extend(_component_features(placed.comp))
    features = _dedupe_preserve_order(features)
    if features:
        return _shorten(", ".join(features[:5]), _TITLE_BLOCK_COMMENT3_LIMIT)
    return _shorten(f"{len(layout.placed_ics)} active parts", _TITLE_BLOCK_COMMENT3_LIMIT)


def _root_comment2(sheet_infos: list[dict]) -> str:
    names = [si["alloc"].name for si in sheet_infos]
    shown = names[:6]
    if len(names) > 6:
        shown.append(f"+{len(names) - 6} more")
    return _shorten("; ".join(shown), _TITLE_BLOCK_COMMENT2_LIMIT)


def _root_comment3(sheet_infos: list[dict]) -> str:
    titles = [si["alloc"].title for si in sheet_infos[:4]]
    if not titles:
        return "Top-level overview"
    summary = ", ".join(titles)
    if len(sheet_infos) > 4:
        summary += ", ..."
    return _shorten(f"Sheets: {summary}", _TITLE_BLOCK_COMMENT3_LIMIT)


def _root_sheet_preview_lines(sheet_info: dict) -> list[str]:
    """Return compact preview lines for a root-sheet sheet symbol."""
    alloc = sheet_info["alloc"]
    support_count = len(alloc.bypass_caps) + len(alloc.straps)
    label_count = len(sheet_info.get("labels", set())) + len(sheet_info.get("hier_labels", set()))

    primary_entries = []
    for comp in alloc.components:
        if comp.ref_prefix.upper() in {"R", "C", "L"}:
            continue
        ref = comp.source_ref or comp.ref_prefix
        mpn = comp.source_mpn or comp.mpn or comp.value
        if not mpn:
            continue
        primary_entries.append(f"{ref} {mpn}")
        if len(primary_entries) >= 2:
            break
    if not primary_entries:
        primary_entries.append(f"{len(alloc.components)} components")

    features = []
    for comp in alloc.components:
        features.extend(_component_features(comp))
    features = _dedupe_preserve_order(features)

    lines = [
        _shorten("; ".join(primary_entries), 34),
        _shorten(f"{len(alloc.components)} parts · {support_count} support · {label_count} nets", 34),
    ]
    if features:
        lines.append(_shorten(", ".join(features[:3]), 34))
    return [line for line in lines if line]


def _rendered_bounds_fit(content: str, paper: str, margin: float = _RENDER_FIT_MARGIN) -> bool:
    """Return True when estimated rendered bounds stay within the chosen paper."""
    min_x, min_y, max_x, max_y = estimate_content_bounds(content)
    pw, ph = PAPER_SIZES.get(paper, PAPER_SIZES["A3"])
    usable_h = ph - TITLE_BLOCK_H
    return min_x >= margin and min_y >= margin and max_x <= (pw - margin) and max_y <= (usable_h - margin)


def _rendered_bounds_summary(content: str) -> tuple[float, float, float, float]:
    min_x, min_y, max_x, max_y = estimate_content_bounds(content)
    return (round(min_x, 1), round(min_y, 1), round(max_x, 1), round(max_y, 1))


def _clone_layout_with_paper(layout: SheetLayout, paper: str) -> SheetLayout:
    """Reuse an existing placement on a larger paper without renumbering refs."""
    if layout.paper == paper:
        return layout
    cloned = copy.deepcopy(layout)
    cloned.paper = paper
    return cloned


def _collect_layout_nets(layout: SheetLayout) -> set[str]:
    """Collect all net names that will appear as labels on a rendered sheet."""
    nets = set()
    for placed in layout.placed_ics:
        comp = placed.comp
        nets.update(comp.pin_nets.values())
        nets.update(comp.power_pins.values())
    for pp in layout.placed_passives:
        nets.add(pp.net1)
        nets.add(pp.net2)
    for name, _direction in layout.boundary_ports:
        nets.add(name)
    nets.discard("")
    return nets


def _explicit_boundary_nets(layouts: list[SheetLayout]) -> set[str]:
    """Return non-power nets declared as explicit sheet boundary ports."""
    explicit_boundary_ports: set[str] = set()
    for layout in layouts:
        explicit_boundary_ports.update(
            name for name, _direction in layout.boundary_ports if name and not _is_power_net(name)
        )
    return explicit_boundary_ports


def _compute_boundary_nets(layouts: list[SheetLayout], interface_policy: str = "inferred") -> set[str]:
    """Return non-power nets that should become sheet interfaces.

    ``explicit`` only exports nets declared via ``boundary_ports``.
    ``inferred`` preserves the older behavior of also promoting any non-power
    net that appears on two or more sheets.
    """
    interface_policy = _normalize_interface_policy(interface_policy)
    explicit_boundary_ports = _explicit_boundary_nets(layouts)
    if interface_policy == "explicit":
        return explicit_boundary_ports

    net_to_sheets: dict[str, int] = {}
    for layout in layouts:
        for net in _collect_layout_nets(layout):
            net_to_sheets[net] = net_to_sheets.get(net, 0) + 1

    return {
        net
        for net, count in net_to_sheets.items()
        if (count >= 2 or net in explicit_boundary_ports) and not _is_power_net(net)
    }


def _merge_label_shape(existing: str | None, new_shape: str | None) -> str:
    """Combine multiple observed label shapes for the same net conservatively."""
    if not new_shape:
        return existing or "bidirectional"
    if not existing or existing == new_shape:
        return new_shape
    return "bidirectional"


def _extract_label_shapes(content: str, keyword: str) -> dict[str, str]:
    """Return ``label_name -> merged_shape`` for the given label keyword."""
    shapes: dict[str, str] = {}
    pattern = re.compile(rf'\({keyword}\s+"([^"]+)"\s+\(shape\s+(\w+)\)')
    for match in pattern.finditer(content):
        name = match.group(1)
        shape = match.group(2)
        shapes[name] = _merge_label_shape(shapes.get(name), shape)
    return shapes


def _report_validation_results(results) -> None:
    total_issues = sum(len(result.issues) for result in results)
    if not total_issues:
        print("  Validation: no algebraic circuit issues detected")
    for result in results:
        line = f"  Validation {result.status}: {result.label}"
        if result.issues:
            line += f" ({len(result.issues)} issue(s))"
        print(line)
        for issue in result.issues[:4]:
            print(f"    {issue.level.upper()} [{issue.code}] {issue.ref} {issue.mpn}: {issue.message}")
        if len(result.issues) > 4:
            print(f"    ... and {len(result.issues) - 4} more")


def _pick_root_sheet_geometry(sheet_count: int, sheet_w: float, sheet_h: float):
    x_margin = snap(30)
    y_start = snap(40)
    x_spacing = snap(sheet_w + 15)
    y_spacing = snap(sheet_h + 15)
    for paper in ("A3", "A2", "A1", "A0"):
        pw, ph = PAPER_SIZES[paper]
        usable_w = max(1.0, pw - x_margin - 30)
        cols = max(1, int((usable_w + 15) // x_spacing))
        rows = math.ceil(sheet_count / cols)
        bottom = y_start + (rows - 1) * y_spacing + sheet_h + 10
        if bottom <= ph - TITLE_BLOCK_H:
            return paper, x_margin, y_start, cols, x_spacing, y_spacing
    cols = max(1, int((PAPER_SIZES["A0"][0] - x_margin - 30 + 15) // x_spacing))
    return "A0", x_margin, y_start, cols, x_spacing, y_spacing


def generate_from_components(
    components: list[ComponentDef],
    output_dir: str = ".",
    project_name: str = "project",
    company: str = "",
    stable_uuids: bool | None = None,
    post_allocate=None,
    validate: bool = True,
    pcb: bool = False,
    hierarchical: bool = False,
    interface_policy: str | None = None,
    presentation_wiring_policy: PresentationWiringPolicy | dict | None = None,
    score: bool = False,
) -> list[str]:
    """Generate KiCad schematics from a list of ComponentDefs.

    Single-sheet designs produce one .kicad_sch file.
    Multi-sheet designs produce:
      - A root schematic ({project_name}.kicad_sch) with sheet symbols
      - One sub-sheet per functional group ({name}.kicad_sch)
      - Cross-sheet stub labels so power/signal nets connect between sheets

    When ``hierarchical=True``, multi-sheet designs use KiCad hierarchical
    labels on sub-sheets and matching sheet pins on the root schematic's
    sheet symbols for selected non-power interface nets.  Power nets
    (GND, VDD_*, VCC*, ...) remain as global labels per KiCad convention.

    ``interface_policy`` selects how those interface nets are chosen:
    - ``"explicit"``: only nets declared via template ``boundary_ports``
    - ``"inferred"``: explicit ports plus any non-power net seen on 2+ sheets

    post_allocate: optional callable(sheets) to modify SheetAllocations
        (e.g., add sheet_annotations) before rendering.

    Returns list of generated file paths.
    """
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    stable_mode = _env_flag_enabled() if stable_uuids is None else stable_uuids
    seed = None
    if stable_mode:
        identities = "|".join(f"{idx}:{_component_identity(comp)}" for idx, comp in enumerate(components))
        seed = f"{project_name}|{identities}"
    configure_deterministic_uids(seed)

    try:
        reset_ref_counters()
        root_uuid = uid(f"root:{project_name}")

        # 0. Auto-generate bypass caps for ICs that have power pins but none defined
        auto_decoupled = auto_generate_bypass_caps(components)
        if auto_decoupled:
            print(f"  Auto-generated bypass caps for {auto_decoupled} IC(s) with power pins")

        _resolve_late_pin_maps(components)

        if validate:
            validation_results = run_validation_checks(components)
            _report_validation_results(validation_results)
        else:
            validation_results = None

        resolved_presentation_wiring_policy = normalize_presentation_wiring_policy(presentation_wiring_policy)

        # 1. Allocate components to sheets
        sheets = allocate_sheets(components)
        for sheet_alloc in sheets:
            if getattr(sheet_alloc, "presentation_wiring_policy", None) is None:
                sheet_alloc.presentation_wiring_policy = resolved_presentation_wiring_policy
        if post_allocate:
            post_allocate(sheets)
        _logger.info("Allocated %d components to %d sheet(s)", len(components), len(sheets))

        # 1b. Layout all sheets first (needed for boundary net computation)
        layouts = []
        for sheet_alloc in sheets:
            layout = layout_sheet(sheet_alloc, presentation_wiring_policy=resolved_presentation_wiring_policy)
            layouts.append(layout)
            _logger.info(
                "  %s: %d ICs, %d passives on %s",
                sheet_alloc.name,
                len(layout.placed_ics),
                len(layout.placed_passives),
                layout.paper,
            )

        # 1b'. Optional aesthetics scoring
        if score:
            from .scorer import score_project as _score_project

            project_score = _score_project(layouts)
            print(f"  Aesthetics: {project_score['grade']} ({project_score['total']}/100)")
            for _sh in project_score["sheets"]:
                print(f"    {_sh['sheet']}: {_sh['grade']} ({_sh['total']})")

        # 1c. Compute boundary nets for hierarchical mode
        boundary_nets: set[str] = set()
        use_hierarchy = hierarchical and len(sheets) > 1
        resolved_interface_policy = _normalize_interface_policy(interface_policy)
        if use_hierarchy:
            boundary_nets = _compute_boundary_nets(layouts, resolved_interface_policy)
            if boundary_nets:
                _logger.info(
                    "  Hierarchical mode: %d boundary nets (%s)",
                    len(boundary_nets),
                    resolved_interface_policy,
                )

        # 2. Generate each sub-sheet, collecting label info
        sheet_infos = []  # (alloc, uuid, filepath, labels_set)
        for i, (sheet_alloc, layout) in enumerate(zip(sheets, layouts)):
            sheet_uuid = uid(f"sheet:{sheet_alloc.name}:{i}")
            page_num = i + 2 if len(sheets) > 1 else 1  # page 1 = root for multi-sheet

            trial_layout = layout
            content = ""
            start_idx = _PAPER_ORDER.index(layout.paper) if layout.paper in _PAPER_ORDER else 0
            promoted_from = layout.paper

            for paper in _PAPER_ORDER[start_idx:]:
                trial_layout = _clone_layout_with_paper(layout, paper)
                content = _render_sheet(
                    trial_layout,
                    project_name,
                    company,
                    root_uuid,
                    sheet_uuid,
                    page_num,
                    boundary_nets=boundary_nets if use_hierarchy else None,
                )
                content = center_content(content, trial_layout.paper)
                if _rendered_bounds_fit(content, trial_layout.paper):
                    break
            else:
                bounds = _rendered_bounds_summary(content)
                print(
                    f"WARNING: sheet '{sheet_alloc.name}' still exceeds rendered page bounds "
                    f"on {trial_layout.paper}: {bounds}"
                )

            if trial_layout.paper != promoted_from:
                print(
                    f"  Promoted sheet '{sheet_alloc.name}' from {promoted_from} "
                    f"to {trial_layout.paper} based on rendered text/symbol bounds"
                )
            layout = trial_layout

            filename = f"{project_name}.kicad_sch" if len(sheets) == 1 else f"{sheet_alloc.name}.kicad_sch"
            filepath = output_path / filename
            # Validate S-expression parenthesis balance before writing
            _validate_sexpr_balance(content, filename)

            filepath.write_text(content, encoding="utf-8", newline="")

            # Collect all label names on this sheet (global + hierarchical)
            label_names = set(re.findall(r'\(global_label "([^"]+)"', content))
            hier_label_shapes = _extract_label_shapes(content, "hierarchical_label")
            hier_labels = set(hier_label_shapes)

            sheet_infos.append(
                {
                    "alloc": sheet_alloc,
                    "uuid": sheet_uuid,
                    "filepath": filepath,
                    "filename": filename,
                    "labels": label_names,
                    "hier_labels": hier_labels,
                    "hier_label_shapes": hier_label_shapes,
                    "page_num": page_num,
                }
            )
            label_count = len(label_names) + len(hier_labels)
            _logger.info("  -> %s (%d labels)", filepath, label_count)

        generated_files = [str(si["filepath"]) for si in sheet_infos]

        # 3. Multi-sheet: add cross-sheet stubs + generate root schematic
        if len(sheets) > 1:
            _add_cross_sheet_stubs(sheet_infos)
            root_file = _generate_root_schematic(
                sheet_infos,
                output_path,
                project_name,
                company,
                root_uuid,
                hierarchical=use_hierarchy,
            )
            generated_files.insert(0, str(root_file))
            _logger.info("  -> %s (root schematic)", root_file)

        # 4. Generate design report
        if validate:
            from .report import generate_report

            report_path = output_path / f"{project_name}_report.md"
            generate_report(
                components,
                validation_results=validation_results,
                output_path=report_path,
                metadata={"project": project_name, "company": company},
            )
            generated_files.append(str(report_path))
            _logger.info("  -> %s (design report)", report_path)

        # 5. Generate PCB placement hints (optional)
        if pcb:
            from .pcb_export import generate_pcb_placement

            pcb_file, _placements = generate_pcb_placement(components, output_path, project_name)
            generated_files.append(pcb_file)

        return generated_files
    finally:
        disable_deterministic_uids()


def _add_cross_sheet_stubs(sheet_infos: list[dict]):
    """Report shared global labels without emitting presentation-cluttering stubs.

    The engine already uses KiCad global labels for all inter-sheet nets, so
    injecting unattached duplicate labels onto unrelated sheets is redundant
    and makes dense pages significantly harder to read.
    """
    # Collect label → set of sheet indices
    label_to_sheets = {}
    for i, si in enumerate(sheet_infos):
        for label in si["labels"]:
            if label not in label_to_sheets:
                label_to_sheets[label] = set()
            label_to_sheets[label].add(i)
    cross_sheet = sum(1 for sheets in label_to_sheets.values() if len(sheets) >= 2)
    single_sheet_power = [
        label
        for label, sheets in label_to_sheets.items()
        if len(sheets) == 1
        and (label == "GND" or label.startswith(("VDD_", "VCC", "VBUS", "VIN", "VDDA", "MGT", "VCCO")))
    ]

    # Count hierarchical labels (present when hierarchical=True)
    total_hier = sum(len(si.get("hier_labels", set())) for si in sheet_infos)
    hier_suffix = f", {total_hier} hierarchical" if total_hier else ""

    if single_sheet_power:
        print(
            f"  Cross-sheet labels: {cross_sheet} shared nets, "
            f"{len(single_sheet_power)} single-sheet power nets kept local{hier_suffix}"
        )
    else:
        print(f"  Cross-sheet labels: {cross_sheet} shared nets{hier_suffix}")


def _generate_root_schematic(
    sheet_infos: list[dict],
    output_path: Path,
    project_name: str,
    company: str,
    root_uuid: str,
    hierarchical: bool = False,
) -> Path:
    """Generate the root/top-level schematic with sheet symbols.

    The root schematic contains:
    - One sheet symbol per sub-sheet, arranged in a grid
    - Title block with project info
    - When ``hierarchical=True``, sheet symbols include ``(pin ...)`` entries
      matching each sub-sheet's hierarchical labels, plus short parent-sheet
      stubs with global labels so matching boundary nets are actually tied
      together on the root sheet.
    """
    pin_spacing = 2.54  # mm between hierarchical pins on the sheet symbol

    # Compute minimum sheet symbol height based on hierarchical pin count
    base_sheet_h = 20  # mm, minimum symbol height
    max_pins = 0
    if hierarchical:
        for si in sheet_infos:
            max_pins = max(max_pins, len(si.get("hier_labels", set())))
    # Each pin needs pin_spacing mm; add margins top and bottom
    needed_h = max_pins * pin_spacing + 2 * pin_spacing if max_pins > 0 else 0
    sheet_h = max(base_sheet_h, snap(needed_h))

    sheet_w = 50  # mm, symbol width
    paper, x_start, y_start, cols, x_spacing, y_spacing = _pick_root_sheet_geometry(len(sheet_infos), sheet_w, sheet_h)
    header = sexpr_header(
        title=f"{project_name} — Top Level",
        subtitle=f"{len(sheet_infos)} sheets",
        paper=paper,
        company=company,
        project=project_name,
        comment2=_root_comment2(sheet_infos),
        comment3=_root_comment3(sheet_infos),
        uuid_str=root_uuid,
    )

    parts = [header]
    parts.append("  (lib_symbols)\n")
    root_wires: list[str] = []
    root_labels: list[str] = []
    root_preview_text: list[str] = []

    for i, si in enumerate(sheet_infos):
        row = i // cols
        col = i % cols
        sx = snap(x_start + col * x_spacing)
        sy = snap(y_start + row * y_spacing)
        sheet_uuid = si["uuid"]
        filename = si["filename"]
        name = si["alloc"].name

        pin_lines = ""
        if hierarchical:
            pin_side = "R"
            if cols > 1 and col == cols - 1:
                pin_side = "L"
            pin_x = snap(sx + sheet_w) if pin_side == "R" else snap(sx)
            pin_angle_for_label = 180 if pin_side == "R" else 0
            hier_label_shapes = si.get("hier_label_shapes", {})
            for j, label_name in enumerate(sorted(hier_label_shapes)):
                pin_y = snap(sy + pin_spacing + j * pin_spacing)
                label_shape = hier_label_shapes.get(label_name, "bidirectional")
                pin_lines += sexpr_sheet_pin(label_name, shape=label_shape, side=pin_side, x=pin_x, y=pin_y) + "\n"
                connect_pin_to_label(
                    pin_x,
                    pin_y,
                    pin_angle_for_label,
                    label_name,
                    root_wires,
                    root_labels,
                    shape=label_shape,
                    wire_len=5.08,
                )

        parts.append(f'''  (sheet (at {sx:.2f} {sy:.2f}) (size {sheet_w:.2f} {sheet_h:.2f})
    (stroke (width 0.1524) (type solid))
    (fill (color 255 255 255 1.0))
    (uuid "{sheet_uuid}")
    (property "Sheetname" "{name}" (at {sx:.2f} {sy - 1.27:.2f} 0)
      (effects (font (size 1.27 1.27)) (justify left bottom))
    )
    (property "Sheetfile" "{filename}" (at {sx:.2f} {sy + sheet_h + 1.27:.2f} 0)
      (effects (font (size 1.0 1.0)) (justify left top))
    )
{pin_lines}  )
''')

        preview_x = snap(sx + sheet_w / 2.0)
        preview_y = sy + 5.08
        for line in _root_sheet_preview_lines(si):
            root_preview_text.append(text_annotation(line, preview_x, preview_y, size=1.0))
            preview_y += 3.18

    parts.extend(root_wires)
    parts.extend(root_labels)
    parts.extend(root_preview_text)

    # Title text
    parts.append(sheet_title_text(f"{project_name}", f"Top-level overview — {len(sheet_infos)} sub-sheets", x=20, y=15))

    # Sheet instances for root
    parts.append(f'  (sheet_instances\n    (path "/{root_uuid}/" (page "1"))\n  )\n')
    parts.append(")")

    root_file = output_path / f"{project_name}.kicad_sch"
    root_file.write_text("\n".join(parts), encoding="utf-8", newline="")
    return root_file


def generate_from_bom(
    bom_csv: str,
    output_dir: str = ".",
    project_name: str = "project",
    company: str = "",
    registry: ComponentRegistry = None,
    kicad_lib=None,
    stable_uuids: bool | None = None,
    post_allocate=None,
    post_bom_resolve=None,
    validate: bool = True,
    pcb: bool = False,
    hierarchical: bool = False,
    interface_policy: str | None = None,
    presentation_wiring_policy: PresentationWiringPolicy | dict | None = None,
) -> list[str]:
    """Generate KiCad schematics from a BOM CSV file.

    Auto-detects BOM format (KiCad, DigiKey, LCSC, generic CSV/TSV).
    Looks up each line item in the component registry.
    Auto-generates passive components (C/R/L) from ref + value.
    Falls back to kicad_lib (KiCadLibrary) for parts not in the registry.

    post_bom_resolve: optional callable(components) to modify component instances
        after BOM lookup but before sheet allocation (e.g., per-instance net overlays).
    post_allocate: optional callable(sheets) to modify SheetAllocations before rendering.
    """
    if registry is None:
        registry = BUILTIN_REGISTRY

    bom_rows = parse_bom_csv(bom_csv)
    print(f"Parsed {len(bom_rows)} BOM lines from {bom_csv}")

    components = []
    unknown = []
    passives_generated = 0
    lib_resolved = 0

    for row in bom_rows:
        qty = max(1, row.quantity or 1)

        # Try registry lookup by MPN first, then by value
        comp = registry.get(row.mpn)
        if not comp and row.value:
            comp = registry.get(row.value)

        if comp:
            components.extend(_apply_bom_overlay(comp, row, idx) for idx in range(qty))
            continue

        # Try generating a passive component from ref + value
        passive = infer_passive_component(row.ref, row.value, row.footprint)
        if passive:
            components.extend(_apply_bom_overlay(passive, row, idx) for idx in range(qty))
            passives_generated += qty
            continue

        # Try KiCad library fallback
        if kicad_lib and row.mpn:
            comp = kicad_lib.get_component(row.mpn)
            if comp:
                components.extend(_apply_bom_overlay(comp, row, idx) for idx in range(qty))
                lib_resolved += qty
                continue

        if row.mpn:
            unknown.append((row.ref or "(no-ref)", row.mpn, row.value, qty))

    if passives_generated:
        print(f"  Auto-generated {passives_generated} passive component(s)")
    if lib_resolved:
        print(f"  Resolved {lib_resolved} component(s) from KiCad library")

    if unknown:
        unknown_qty = sum(qty for _, _, _, qty in unknown)
        print(f"  WARNING: {len(unknown)} unknown BOM line(s) ({unknown_qty} total component(s)) not in registry:")
        for ref, mpn, val, qty in unknown[:10]:
            print(f"    {ref}: {mpn} ({val}) x{qty}")
        if len(unknown) > 10:
            print(f"    ... and {len(unknown) - 10} more")

    if not components:
        print("ERROR: No known components found in BOM")
        return []

    if post_bom_resolve:
        post_bom_resolve(components)

    return generate_from_components(
        components,
        output_dir,
        project_name,
        company,
        stable_uuids=stable_uuids,
        post_allocate=post_allocate,
        validate=validate,
        pcb=pcb,
        hierarchical=hierarchical,
        interface_policy=interface_policy,
        presentation_wiring_policy=presentation_wiring_policy,
    )


def _get_pin_side(pangle: int) -> str:
    """Return 'left', 'right', 'top', or 'bottom' based on pin angle.

    KiCad pin angles: 0=left, 90=up, 180=right, 270=down.
    """
    if pangle == 0:
        return "left"
    elif pangle == 90:
        return "top"
    elif pangle == 180:
        return "right"
    elif pangle == 270:
        return "bottom"
    return "unknown"


def _pin_type_to_label_shape(ptype: str) -> str | None:
    """Map KiCad pin type to label shape (for Phase 4: Label Direction).

    Returns the shape parameter for connect_pin_to_label():
    - "input" → "input" (right-pointing arrow)
    - "output" → "output" (left-pointing arrow)
    - "bidirectional" → "bidirectional" (double arrow)
    - "tri_state" → "tri_state" (open arrow)
    - "passive" → "bidirectional" (treat as passive/generic)
    - "power_in" → None (uses power symbol, not label)
    - "power_out" → None (uses power symbol, not label)
    - "unspecified" → "bidirectional" (default fallback)

    KiCad pin types: input, output, bidirectional, tri_state, passive,
    power_in, power_out, unspecified, opencollector, openemitter, noconnect.
    """
    shape_map = {
        "input": "input",
        "output": "output",
        "bidirectional": "bidirectional",
        "tri_state": "tri_state",
        "passive": "bidirectional",
        "power_in": None,  # These use power symbols, not labels
        "power_out": None,
        "unspecified": "bidirectional",
        "opencollector": "output",
        "openemitter": "output",
        "noconnect": None,
    }
    return shape_map.get(ptype, "bidirectional")


def _truthful_bus_label(nets_in_group: list[str]) -> str | None:
    """Return a truthful vector label when the members form a real numeric bus.

    Examples:
        DDR_DQ0..DDR_DQ15 -> DDR_DQ[0..15]
        ETH_RXD0..ETH_RXD3 -> ETH_RXD[0..3]

    Returns ``None`` for mixed or non-numeric groups such as SPI signal names.
    """
    if not nets_in_group:
        return None

    parsed: list[tuple[str, int]] = []
    for net_name in nets_in_group:
        match = re.match(r"^(.*?)(\d+)$", net_name)
        if not match:
            return None
        parsed.append((match.group(1), int(match.group(2))))

    prefixes = {prefix for prefix, _idx in parsed}
    if len(prefixes) != 1:
        return None

    indices = sorted(idx for _prefix, idx in parsed)
    if indices != list(range(indices[0], indices[-1] + 1)):
        return None

    prefix = parsed[0][0]
    return f"{prefix}[{indices[0]}..{indices[-1]}]"


def _render_bus_group(
    group_name: str,
    nets_in_group: list[str],
    net_coords: dict[str, list[tuple]],
    orientation: str,  # "vertical" for left/right, "horizontal" for top/bottom
) -> tuple[list[str], list[str], list[str]]:
    """Render a bus group as vertical/horizontal bus wire + entries + label.

    Returns (bus_wires, bus_entries, bus_labels) as S-expression strings.

    Args:
        group_name: Name of the group (e.g., "DDR_DATA")
        nets_in_group: List of net names in this group
        net_coords: Map net_name -> [(cx, cy, pangle[, ptype]), ...]
        orientation: "vertical" for left/right sides, "horizontal" for top/bottom

    Only processes nets that have coordinates. Returns empty lists if insufficient data.
    """
    from .primitives import sexpr_bus, sexpr_bus_entry, sexpr_bus_label

    bus_wires = []
    bus_entries = []
    bus_labels = []

    # Collect all valid coordinates for nets in this group
    all_points = []
    for net in nets_in_group:
        if net in net_coords:
            all_points.extend(net_coords[net])

    if not all_points:
        return [], [], []

    # Sort by position (Y for vertical buses, X for horizontal)
    if orientation == "vertical":
        all_points.sort(key=lambda p: p[1])  # Sort by Y
    else:
        all_points.sort(key=lambda p: p[0])  # Sort by X

    # Get bounds and center for bus label placement
    ys = [p[1] for p in all_points]
    xs = [p[0] for p in all_points]
    y_min, y_max = min(ys), max(ys)
    x_min, x_max = min(xs), max(xs)
    y_center = snap((y_min + y_max) / 2)
    x_center = snap((x_min + x_max) / 2)

    # Determine bus wire position and entry angles
    if orientation == "vertical":
        # LEFT/RIGHT side: vertical bus
        # Dense sides get extra clearance so the bus spine sits outside the pin wall.
        stub_x_offset = 7.62 if len(all_points) >= 8 else 5.08
        # Bus position = stub + 2.54mm further
        bus_offset = stub_x_offset + 2.54

        # Get dominant pin angle to determine left vs right
        dominant_angle = all_points[0][2]  # Use first point's angle
        if dominant_angle == 0:  # Left side (wires extend left)
            bus_x = snap(x_min - bus_offset)
            entry_angle = _bus_entry_angle_for_side("left")
            label_x = snap(bus_x - 1.27)
            label_angle = 0
        else:  # Right side (wires extend right, angle=180)
            bus_x = snap(x_max + bus_offset)
            entry_angle = _bus_entry_angle_for_side("right")
            label_x = snap(bus_x + 1.27)
            label_angle = 180

        # Bus wire: vertical from y_min to y_max
        bus_wires.append(sexpr_bus(bus_x, y_min, bus_x, y_max))

        # Bus entries: 45° from each pin to bus wire
        for point in all_points:
            cx, cy, pangle = point[:3]
            pin_stub_x = snap(cx - stub_x_offset) if pangle == 0 else snap(cx + stub_x_offset)
            bus_entries.append(sexpr_bus_entry(pin_stub_x, cy, angle=entry_angle))
            # Connect bus entry to bus wire
            bus_wires.append(sexpr_wire(pin_stub_x, cy, bus_x, cy))

        # Bus label: only emit a vector label when it truthfully matches members.
        bus_label = _truthful_bus_label(nets_in_group)
        if bus_label:
            bus_labels.append(sexpr_bus_label(label_x, y_center, bus_label, angle=label_angle))

    else:
        # TOP/BOTTOM side: horizontal bus
        # Dense sides get extra clearance so the bus spine sits outside the pin wall.
        stub_y_offset = 7.62 if len(all_points) >= 8 else 5.08
        # Bus position = stub + 2.54mm further
        bus_offset = stub_y_offset + 2.54

        # Get dominant pin angle
        dominant_angle = all_points[0][2]  # 90=up, 270=down
        if dominant_angle == 90:  # Top (wires extend up)
            bus_y = snap(y_min - bus_offset)
            entry_angle = _bus_entry_angle_for_side("top")
            label_y = snap(bus_y - 1.27)
            label_angle = 0
        else:  # Bottom (wires extend down, angle=270)
            bus_y = snap(y_max + bus_offset)
            entry_angle = _bus_entry_angle_for_side("bottom")
            label_y = snap(bus_y + 1.27)
            label_angle = 180

        # Bus wire: horizontal from x_min to x_max
        bus_wires.append(sexpr_bus(x_min, bus_y, x_max, bus_y))

        # Bus entries: 45° from each pin to bus wire
        for point in all_points:
            cx, cy, pangle = point[:3]
            pin_stub_y = snap(cy - stub_y_offset) if pangle == 90 else snap(cy + stub_y_offset)
            bus_entries.append(sexpr_bus_entry(cx, pin_stub_y, angle=entry_angle))
            # Connect bus entry to bus wire
            bus_wires.append(sexpr_wire(cx, pin_stub_y, cx, bus_y))

        # Bus label: only emit a vector label when it truthfully matches members.
        bus_label = _truthful_bus_label(nets_in_group)
        if bus_label:
            bus_labels.append(sexpr_bus_label(x_center, label_y, bus_label, angle=label_angle))

    return bus_wires, bus_entries, bus_labels


def _bus_entry_angle_for_side(side: str) -> int:
    """Return a side-aware entry angle for stub-anchored bus entries."""
    return {
        "left": 270,
        "right": 0,
        "top": 270,
        "bottom": 90,
    }.get(side, 0)


def _should_render_bus_group(group_name: str, nets_in_group: list[str]) -> bool:
    """Return True when a classified net group should render as a bus."""
    return len(nets_in_group) >= 4 and group_name != "_misc"


def _render_sheet(
    layout: SheetLayout,
    project_name: str,
    company: str,
    root_uuid: str,
    sheet_uuid: str,
    page_num: int,
    boundary_nets: set[str] | None = None,
) -> str:
    """Render a SheetLayout into a .kicad_sch string.

    When *boundary_nets* is provided (non-None set), nets in that set use
    ``hierarchical_label`` instead of ``global_label``.  Power nets and
    sheet-local nets continue to use ``global_label``.
    """
    header = sexpr_header(
        title=layout.title,
        subtitle=f"{len(layout.placed_ics)} components",
        paper=layout.paper,
        company=company,
        project=project_name,
        comment2=_sheet_comment2(layout),
        comment3=_sheet_comment3(layout),
        uuid_str=sheet_uuid,
    )

    lib_symbols = []
    instances = []
    labels = []
    power_instances = []
    power_lib_names = set()
    no_connects = []
    wires = []

    # Signal coordinates across the whole sheet:
    # net_name -> list of (cx, cy, pangle, ptype, wire_len) tuples
    signal_pin_coords: dict[str, list[tuple[float, float, int, str, float]]] = {}
    # Component-local coordinates for bus clustering:
    # ref -> {net_name: [(cx, cy, pangle, ptype), ...]}
    component_signal_pin_coords: dict[str, dict[str, list[tuple[float, float, int, str]]]] = {}

    def _label_fn(net_name):
        """Return the appropriate label-emitter for *net_name*."""
        if boundary_nets and net_name in boundary_nets:
            return connect_pin_to_hierarchical_label
        return connect_pin_to_label

    # Track which lib_symbols we've emitted
    emitted_symbols = set()
    # IC pin connection points for local wiring: {ref: {net: [(x, y)]}}
    pin_point_map: dict[str, dict[str, list[tuple[float, float]]]] = {}
    placed_ic_map: dict[str, object] = {}

    # --- Place ICs ---
    for placed in layout.placed_ics:
        comp = placed.comp

        sym_name, sym_sexpr = _render_symbol_name_and_sexpr(comp)

        # Create and emit lib_symbol if not already done
        if sym_name not in emitted_symbols:
            lib_symbols.append(sym_sexpr)
            emitted_symbols.add(sym_name)

        # Place component instance
        body_left, _body_top, body_right, _body_bottom = component_body_bounds(placed)
        property_center_x = snap((body_left + body_right) / 2.0)
        instances.append(
            place_component(
                sym_name,
                placed.ref,
                comp.value,
                comp.footprint,
                placed.x,
                placed.y,
                angle=placed.angle,
                project_name=project_name,
                root_uuid=root_uuid,
                sheet_uuid=sheet_uuid,
                property_center_x=property_center_x,
            )
        )

        # Get pin positions from the symbol S-expression
        pin_pos = get_pin_positions(sym_sexpr, sym_name)
        body_rects = _symbol_body_rects(sym_sexpr)
        pin_stub_lengths = _dense_pin_stub_lengths(comp, pin_pos, body_rects)

        # Resolve pin_map_builder for BGA ICs (late evaluation)
        if comp.pin_map_builder and not comp.pin_nets and not comp.power_pins:
            all_nets = comp.pin_map_builder(pin_pos)
            for pin_num, net in all_nets.items():
                if net in ("GND",) or net.startswith(("VDD", "VCC", "VBUS", "VDDA", "MGT")):
                    comp.power_pins[pin_num] = net
                else:
                    comp.pin_nets[pin_num] = net

        handled = set()

        # Collect pin connection points for local wiring and component-local
        # bus clustering on this IC.
        ic_pin_points: dict[str, list[tuple[float, float]]] = {}
        ic_signal_pin_coords: dict[str, list[tuple[float, float, int, str]]] = {}

        # Signal pins -> collect coordinates for bus grouping + label direction
        for pin_num, net_name in comp.pin_nets.items():
            if pin_num in pin_pos:
                px, py, pangle, plen, pname, ptype = pin_pos[pin_num]
                cx, cy = pin_connection_point(placed.x, placed.y, px, py, pangle, plen)
                wlen = pin_stub_lengths.get(pin_num, _safe_label_stub_length(px, py, pangle, body_rects))
                signal_pin_coords.setdefault(net_name, []).append((cx, cy, pangle, ptype, wlen))
                ic_signal_pin_coords.setdefault(net_name, []).append((cx, cy, pangle, ptype))
                ic_pin_points.setdefault(net_name, []).append((cx, cy))
                handled.add(pin_num)

        # Power pins -> power symbol instances
        for pin_num, net_name in comp.power_pins.items():
            if pin_num in pin_pos:
                px, py, pangle, plen, pname, ptype = pin_pos[pin_num]
                cx, cy = pin_connection_point(placed.x, placed.y, px, py, pangle, plen)
                wire_len = pin_stub_lengths.get(pin_num, _safe_label_stub_length(px, py, pangle, body_rects))

                # Create wire stub (cx -> wx based on pin angle)
                if pangle == 0:
                    wx, wy = cx - wire_len, cy
                elif pangle == 180:
                    wx, wy = cx + wire_len, cy
                elif pangle == 270:
                    wx, wy = cx, cy - wire_len
                elif pangle == 90:
                    wx, wy = cx, cy + wire_len
                else:
                    wx, wy = cx - wire_len, cy

                wires.append(sexpr_wire(cx, cy, wx, wy))

                # Add power symbol instance at stub endpoint
                from .primitives import sexpr_power_instance

                power_instances.append(
                    sexpr_power_instance(
                        net_name,
                        wx,
                        wy,
                        pangle,
                        project_name=project_name,
                        root_uuid=root_uuid,
                        sheet_uuid=sheet_uuid,
                    )
                )
                power_lib_names.add(net_name)

                ic_pin_points.setdefault(net_name, []).append((cx, cy))
                handled.add(pin_num)

        # Classify and handle remaining (unconnected) pins
        nc_intent_notes: list[str] = []
        for pin_num in pin_pos:
            if pin_num not in handled:
                px, py, pangle, plen, pname, ptype = pin_pos[pin_num]
                cx, cy = pin_connection_point(placed.x, placed.y, px, py, pangle, plen)
                _action, level, reason = _classify_unhandled_pin(comp, pin_num, pname, ptype)
                no_connects.append(sexpr_no_connect(cx, cy))
                if level == "error":
                    _logger.error("%s (%s): %s", placed.ref, comp.mpn, reason)
                elif level == "warning":
                    _logger.warning("%s (%s): %s", placed.ref, comp.mpn, reason)
                    nc_intent_notes.append(f"{pname}({pin_num}): NC")
        # Annotate the schematic with NC intent summary for non-trivial cases
        if nc_intent_notes and len(nc_intent_notes) <= 8:
            comp.annotations.append("Unused: " + ", ".join(nc_intent_notes))

        # Store pin points for local wiring by parent ref
        pin_point_map[placed.ref] = ic_pin_points
        component_signal_pin_coords[placed.ref] = ic_signal_pin_coords
        placed_ic_map[placed.ref] = placed

    # --- Detect and render bus groups for signal pins ---
    # Buses are a local presentation aid around one symbol cluster. They do not
    # replace the real per-net labels that carry named connectivity.
    bus_wires_all = []
    bus_entries_all = []
    bus_labels_all = []
    bus_member_points: set[tuple[str, float, float, int, str]] = set()

    for placed in layout.placed_ics:
        local_signal_coords = component_signal_pin_coords.get(placed.ref, {})
        if not local_signal_coords:
            continue

        bus_groups: dict[tuple[str, str], list[str]] = {}
        for net_name, coords in local_signal_coords.items():
            if not coords:
                continue
            side = _get_pin_side(coords[0][2])
            group_name, _sort_idx = classify_net_group(net_name)
            bus_groups.setdefault((side, group_name), []).append(net_name)

        for (side, group_name), nets_in_group in bus_groups.items():
            unique_nets = sorted(set(nets_in_group), key=classify_net_group)
            if not _should_render_bus_group(group_name, unique_nets):
                continue
            orientation = "vertical" if side in ("left", "right") else "horizontal"
            bwires, bentries, blabels = _render_bus_group(group_name, unique_nets, local_signal_coords, orientation)
            bus_wires_all.extend(bwires)
            bus_entries_all.extend(bentries)
            bus_labels_all.extend(blabels)
            for net_name in unique_nets:
                for cx, cy, pangle, ptype in local_signal_coords.get(net_name, []):
                    bus_member_points.add((net_name, cx, cy, pangle, ptype))

    # --- Render signal labels (Phase 4: Label Direction) ---
    for net_name, coords in signal_pin_coords.items():
        if not coords:
            continue

        is_bus_member = any(
            (net_name, cx, cy, pangle, ptype) in bus_member_points for cx, cy, pangle, ptype, _wlen in coords
        )
        if is_bus_member:
            # Bus graphics are decorative; keep explicit labels on every member
            # stub so the actual net names remain visible and connected.
            # Use fixed 5.08mm stubs to align with bus entry geometry.
            for cx, cy, pangle, ptype, _wlen in coords:
                shape = _pin_type_to_label_shape(ptype)
                _label_fn(net_name)(cx, cy, pangle, net_name, wires, labels, wire_len=5.08, shape=shape)
            continue

        for cx, cy, pangle, ptype, wlen in coords:
            shape = _pin_type_to_label_shape(ptype)
            _label_fn(net_name)(cx, cy, pangle, net_name, wires, labels, wire_len=wlen, shape=shape)

    # --- Place passives with local wiring to parent IC ---
    local_route_states: dict[str, dict[str, dict]] = {}
    for pp in layout.placed_passives:
        if pp.symbol_variant == "review":
            endpoint_stub_len = 6.35
        elif pp.role == "strap":
            endpoint_stub_len = _STRAP_ENDPOINT_STUB_LEN
        else:
            endpoint_stub_len = 1.27
        # Place the passive component itself
        passive_base = {"C": "C", "R": "R", "L": "L"}[pp.sym_type]
        sym_name = f"{passive_base}_Review" if pp.symbol_variant == "review" else f"{passive_base}_Small"
        instances.append(
            place_component(
                sym_name,
                pp.ref,
                pp.value,
                pp.footprint,
                pp.x,
                pp.y,
                angle=pp.angle,
                project_name=project_name,
                root_uuid=root_uuid,
                sheet_uuid=sheet_uuid,
            )
        )

        (p1_x, p1_y), (p2_x, p2_y) = passive_pin_xy(pp.x, pp.y, pp.angle, pin_span=pp.pin_span)
        p1_angle, p2_angle = passive_pin_angles(pp.angle)

        parent_pins = pin_point_map.get(pp.parent_ref, {})
        parent_pc = placed_ic_map.get(pp.parent_ref)
        parent_body = component_body_bounds(parent_pc) if parent_pc else None
        route_state = local_route_states.setdefault(pp.parent_ref or "_sheet", {})

        use_literal_local = pp.presentation == "literal_local"
        use_topology_local = pp.presentation == "topology_local"

        # Net1 (pin 1): local route only when explicitly requested.
        anchor1 = _nearest_local_anchor(layout, pp.net1, p1_x, p1_y) if use_topology_local else None
        if anchor1 is not None:
            _route_local_connection(
                p1_x, p1_y, anchor1.x, anchor1.y, wires, obstacle=parent_body, route_state=route_state
            )
        else:
            topology_owner1 = (
                _topology_parent_pin_point(parent_pc, parent_pins, pp, pp.net1) if use_topology_local else None
            )
            if topology_owner1 is not None:
                ic_x, ic_y = topology_owner1
                _route_local_connection(p1_x, p1_y, ic_x, ic_y, wires, obstacle=parent_body, route_state=route_state)
            elif use_literal_local and pp.net1 in parent_pins and parent_pins[pp.net1]:
                ic_x, ic_y = parent_pins[pp.net1][0]
                _route_local_connection(p1_x, p1_y, ic_x, ic_y, wires, obstacle=parent_body, route_state=route_state)
            else:
                _render_passive_net_endpoint(
                    pp.net1,
                    p1_x,
                    p1_y,
                    p1_angle,
                    wires,
                    labels,
                    power_instances,
                    power_lib_names,
                    _label_fn,
                    project_name,
                    root_uuid,
                    sheet_uuid,
                    wire_len=endpoint_stub_len,
                )

        # Net2 (pin 2): local route only when explicitly requested.
        anchor2 = _nearest_local_anchor(layout, pp.net2, p2_x, p2_y) if use_topology_local else None
        if anchor2 is not None:
            _route_local_connection(
                p2_x, p2_y, anchor2.x, anchor2.y, wires, obstacle=parent_body, route_state=route_state
            )
        else:
            topology_owner2 = (
                _topology_parent_pin_point(parent_pc, parent_pins, pp, pp.net2) if use_topology_local else None
            )
            if topology_owner2 is not None:
                ic_x, ic_y = topology_owner2
                _route_local_connection(p2_x, p2_y, ic_x, ic_y, wires, obstacle=parent_body, route_state=route_state)
            elif use_literal_local and pp.net2 in parent_pins and parent_pins[pp.net2]:
                ic_x, ic_y = parent_pins[pp.net2][0]
                _route_local_connection(p2_x, p2_y, ic_x, ic_y, wires, obstacle=parent_body, route_state=route_state)
            else:
                _render_passive_net_endpoint(
                    pp.net2,
                    p2_x,
                    p2_y,
                    p2_angle,
                    wires,
                    labels,
                    power_instances,
                    power_lib_names,
                    _label_fn,
                    project_name,
                    root_uuid,
                    sheet_uuid,
                    wire_len=endpoint_stub_len,
                )

    # --- Explicit local anchor labels / power symbols for topology-aware motifs ---
    for anchor in layout.local_net_anchors:
        if anchor.render_mode == "junction":
            continue
        _render_passive_net_endpoint(
            anchor.name,
            anchor.x,
            anchor.y,
            anchor.angle,
            wires,
            labels,
            power_instances,
            power_lib_names,
            _label_fn,
            project_name,
            root_uuid,
            sheet_uuid,
            wire_len=1.27,
        )

    # --- Explicit local wires declared by the subcircuit template ---
    for x1, y1, x2, y2 in layout.local_wires:
        wires.append(sexpr_wire(x1, y1, x2, y2))

    connected_nets = set()
    for placed in layout.placed_ics:
        connected_nets.update(filter(None, placed.comp.pin_nets.values()))
        connected_nets.update(filter(None, placed.comp.power_pins.values()))
    for pp in layout.placed_passives:
        connected_nets.update((pp.net1, pp.net2))

    # --- Explicit boundary ports declared by the subcircuit template ---
    explicit_ports = [
        (name, direction)
        for name, direction in layout.boundary_ports
        if name and not _is_power_net(name) and name not in connected_nets
    ]
    if explicit_ports:
        sheet_w, _sheet_h = PAPER_SIZES.get(layout.paper, PAPER_SIZES["A3"])
        port_anchor_x = snap(sheet_w - 22)
        port_anchor_y = snap(25)
        for i, (name, direction) in enumerate(explicit_ports):
            port_y = snap(port_anchor_y + i * 5.08)
            _label_fn(name)(port_anchor_x, port_y, 0, name, wires, labels, shape=direction)

    # --- Annotations (design rationale text near ICs) ---
    # T197 — Track placed annotation rectangles per sheet so per-IC blocks
    # from adjacent ICs don't overlap. When a new annotation block would
    # collide with an already-placed one, shift it down by 3.81mm steps
    # (max 6 shifts) until clear, or drop the overflow lines if no slot
    # works. This is a soft layout improvement only; it does not change
    # connectivity or component positions.
    annotation_texts = []
    placed_ann_rects: list[tuple[float, float, float, float]] = []  # (x_min, y_min, x_max, y_max)

    def _ann_rect_for_block(
        x: float,
        y: float,
        lines: list[str],
        char_width: float = 1.5,
    ) -> tuple[float, float, float, float]:
        """Estimate bounding rect for a block of annotation lines."""
        max_chars = max((len(line) for line in lines), default=10)
        block_w = max(20.0, max_chars * char_width)
        block_h = max(3.0, len(lines) * 3.0)
        return (x - 1.0, y - 1.5, x + block_w, y + block_h)

    def _rect_overlaps(
        a: tuple[float, float, float, float],
        b: tuple[float, float, float, float],
    ) -> bool:
        return not (a[2] <= b[0] or b[2] <= a[0] or a[3] <= b[1] or b[3] <= a[1])

    def _find_clear_y(
        start_y: float,
        x: float,
        lines: list[str],
        max_shifts: int = 6,
        step: float = 3.81,
    ) -> float | None:
        """Find a Y offset where the annotation block doesn't overlap any placed rect."""
        for shift in range(max_shifts + 1):
            candidate_y = start_y + shift * step
            candidate_rect = _ann_rect_for_block(x, candidate_y, lines)
            if not any(_rect_overlaps(candidate_rect, existing) for existing in placed_ann_rects):
                return candidate_y
        return None

    for placed in layout.placed_ics:
        explanation_lines = component_explanation_lines(placed.comp, placed.ref)
        if not explanation_lines:
            continue
        ann_x = snap(placed.x + 5)
        ann_y_start = component_annotation_start_y(placed.comp, placed.y)
        lines = list(explanation_lines[:5])
        clear_y = _find_clear_y(ann_y_start, ann_x, lines)
        if clear_y is None:
            # No clear slot found within the search window; drop overflow lines
            # rather than emit colliding text.
            continue
        ann_y = clear_y
        rect = _ann_rect_for_block(ann_x, ann_y, lines)
        placed_ann_rects.append(rect)
        for i, line in enumerate(lines):
            line_x = ann_x if i == 0 else snap(ann_x + 1.27)
            line_size = 1.1 if i == 0 else 1.0
            annotation_texts.append(text_annotation(line, line_x, ann_y + i * 3.0, size=line_size))

    # --- Sheet-level annotations (from allocator) ---
    if layout.sheet_annotations:
        ann_x = snap(20)
        ann_y_start = snap(25)
        sheet_lines = list(layout.sheet_annotations)
        clear_y = _find_clear_y(ann_y_start, ann_x, sheet_lines)
        if clear_y is not None:
            placed_ann_rects.append(_ann_rect_for_block(ann_x, clear_y, sheet_lines))
            for i, line in enumerate(sheet_lines):
                annotation_texts.append(text_annotation(line, ann_x, clear_y + i * 3.0, size=1.27))

    # --- Add power symbol lib entries for any power symbols used ---
    if power_lib_names:
        from .primitives import sexpr_power_lib_entry

        for power_net in sorted(power_lib_names):
            lib_symbols.insert(0, sexpr_power_lib_entry(power_net))

    # --- Add PWR_FLAG on each unique power net for KiCad ERC compliance ---
    pwr_flag_nets_placed: set[str] = set()
    pwr_flag_instances: list[str] = []
    for placed in layout.placed_ics:
        for pin_num, net_name in placed.comp.power_pins.items():
            if net_name in pwr_flag_nets_placed:
                continue
            # Find the connection point for this pin to place PWR_FLAG nearby
            sym_name, sym_sexpr = _render_symbol_name_and_sexpr(placed.comp)
            pin_pos = get_pin_positions(sym_sexpr, sym_name)
            if pin_num in pin_pos:
                px, py, pangle, plen, _pname, _ptype = pin_pos[pin_num]
                cx, cy = pin_connection_point(placed.x, placed.y, px, py, pangle, plen)
                pwr_flag_instances.append(
                    sexpr_pwr_flag_instance(
                        cx,
                        cy,
                        project_name=project_name,
                        root_uuid=root_uuid,
                        sheet_uuid=sheet_uuid,
                    )
                )
                pwr_flag_nets_placed.add(net_name)
    if pwr_flag_instances:
        lib_symbols.insert(0, sexpr_pwr_flag_lib_entry())
        power_instances.extend(pwr_flag_instances)

    # --- Title text ---
    title_text = sheet_title_text(layout.title, f"{project_name} — {layout.name}")
    if annotation_texts:
        title_text += "\n" + "\n".join(annotation_texts)

    # Add power instances to the instances list
    instances.extend(power_instances)

    # Add bus notation (Phase 3b): wires go with wires, entries+labels are bus_elements
    wires.extend(bus_wires_all)
    bus_elements = bus_entries_all + bus_labels_all

    return assemble_sheet(
        header,
        lib_symbols,
        instances,
        labels,
        no_connects,
        extras=title_text,
        wires=wires,
        bus_elements=bus_elements,
        project_name=project_name,
        root_uuid=root_uuid,
        sheet_uuid=sheet_uuid,
        page_num=page_num,
    )


# ================================================================
# CLI entry point
# ================================================================
def _resolve_bom_components(
    bom_csv: str,
    project_name: str = "project",
    registry: ComponentRegistry = None,
) -> list[ComponentDef]:
    """Resolve BOM CSV to ComponentDefs without generating schematics.

    Used by non-KiCad export formats that need the component list but not
    the KiCad rendering pipeline.
    """
    if registry is None:
        registry = BUILTIN_REGISTRY

    bom_rows = parse_bom_csv(bom_csv)
    print(f"Parsed {len(bom_rows)} BOM lines from {bom_csv}")

    components = []
    for row in bom_rows:
        qty = max(1, row.quantity or 1)
        comp = registry.get(row.mpn)
        if not comp and row.value:
            comp = registry.get(row.value)
        if comp:
            components.extend(_apply_bom_overlay(comp, row, idx) for idx in range(qty))
            continue
        passive = infer_passive_component(row.ref, row.value, row.footprint)
        if passive:
            components.extend(_apply_bom_overlay(passive, row, idx) for idx in range(qty))
            continue
        if row.mpn:
            # Create a minimal stub ComponentDef for unknown parts
            stub = ComponentDef(mpn=row.mpn, value=row.value or row.mpn, footprint=row.footprint or "")
            components.extend(_apply_bom_overlay(stub, row, idx) for idx in range(qty))

    return components


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Generate KiCad schematics from BOM")
    parser.add_argument("bom", nargs="?", help="BOM CSV file path")
    parser.add_argument("--output", "-o", default=".", help="Output directory")
    parser.add_argument("--project", "-p", default="project", help="Project name")
    parser.add_argument("--company", default="", help="Company name for title block")
    parser.add_argument(
        "--stable-uuids",
        action="store_true",
        help="Use deterministic UUIDs for diff-friendly regeneration",
    )
    parser.add_argument(
        "--validate",
        dest="validate",
        action="store_true",
        default=True,
        help="Run algebraic schematic validation checks (default: enabled)",
    )
    parser.add_argument(
        "--no-validate",
        dest="validate",
        action="store_false",
        help="Skip algebraic schematic validation checks",
    )
    parser.add_argument(
        "--pcb",
        action="store_true",
        help="Generate PCB placement hint file alongside schematics",
    )
    parser.add_argument(
        "--hierarchical",
        action="store_true",
        help="Use hierarchical labels and sheet pins instead of global labels for cross-sheet signal nets",
    )
    parser.add_argument(
        "--interface-policy",
        choices=sorted(_INTERFACE_POLICIES),
        default="inferred",
        help=(
            "How hierarchical mode chooses sheet interfaces: "
            "inferred (all shared nets) or explicit (declared boundary ports only)"
        ),
    )
    parser.add_argument(
        "--export-format",
        choices=["kicad", "altium", "eagle", "netlist"],
        default="kicad",
        help="Output format: kicad (default), altium (SchDoc XML), eagle (.sch XML), netlist (JSON)",
    )
    parser.add_argument(
        "--enrich-parts",
        dest="enrich_parts",
        action="store_true",
        default=False,
        help="Use distributor lookup to enrich YAML project parts with manufacturer/datasheet metadata",
    )
    parser.add_argument(
        "--no-enrich-parts",
        dest="enrich_parts",
        action="store_false",
        help="Disable distributor lookup enrichment for YAML project specs",
    )
    parser.add_argument("--demo", action="store_true", help="Generate ESP32 single-sheet demo")
    parser.add_argument(
        "--demo-multi",
        action="store_true",
        help="Generate multi-sheet IoT demo (power + mcu + sensors + connectors + debug)",
    )
    args = parser.parse_args()

    # --- Resolve components and project metadata ---
    components = None
    project_name = args.project
    company = args.company

    if args.demo_multi:
        # Multi-sheet demo: 9 components → 5 sheets
        from .component_db import BUILTIN_REGISTRY

        components = [
            BUILTIN_REGISTRY.get("USB-C-PWR"),
            BUILTIN_REGISTRY.get("AMS1117-3.3"),
            BUILTIN_REGISTRY.get("ESP32-WROOM-32E"),
            BUILTIN_REGISTRY.get("BME280"),
            BUILTIN_REGISTRY.get("W25Q128JVSIQ"),
            BUILTIN_REGISTRY.get("microSD-slot"),
            BUILTIN_REGISTRY.get("SWD-10PIN"),
            BUILTIN_REGISTRY.get("LED-0603"),
            BUILTIN_REGISTRY.get("LED-0603"),  # second LED
        ]
        components = [c for c in components if c is not None]
        project_name = "IoT_Multi_Sheet"
        company = company or "Demo"
    elif args.demo:
        # Single-sheet demo: 3 components
        from .component_db import BUILTIN_REGISTRY

        components = [
            BUILTIN_REGISTRY.get("USB-C-PWR"),
            BUILTIN_REGISTRY.get("AMS1117-3.3"),
            BUILTIN_REGISTRY.get("ESP32-WROOM-32E"),
        ]
        components = [c for c in components if c is not None]
        project_name = "ESP32_IoT_Demo"
        company = company or "Demo"
    elif args.bom and args.bom.endswith((".yaml", ".yml")):
        from .project_spec import load_project

        components, metadata = load_project(args.bom, enrich_parts=args.enrich_parts)
        if project_name == "project":
            project_name = metadata.get("project", "project")
        company = company or metadata.get("company", "")
    elif args.bom:
        # BOM CSV — for non-kicad exports, resolve to ComponentDefs first
        pass
    else:
        parser.print_help()
        print("\nTry: python -m schematic_engine.generator my_project.yaml -o output/")
        print("     python -m schematic_engine.generator my_bom.csv -o output/")
        print("     python -m schematic_engine.generator --demo")
        sys.exit(1)

    # --- Dispatch to the selected export format ---
    if args.export_format != "kicad":
        from .exporters import export_altium_xml, export_eagle_xml, export_generic_netlist

        # For BOM CSV input, resolve components through the standard pipeline
        if components is None and args.bom:
            resolved = _resolve_bom_components(args.bom, project_name)
            components = resolved

        if not components:
            print("Error: no components resolved for export")
            sys.exit(1)

        output_path = Path(args.output)
        output_path.mkdir(parents=True, exist_ok=True)

        ext_map = {"altium": ".xml", "eagle": ".sch", "netlist": ".json"}
        ext = ext_map[args.export_format]
        outfile = str(output_path / f"{project_name}{ext}")

        if args.export_format == "altium":
            result = export_altium_xml(components, outfile, project_name, company)
        elif args.export_format == "eagle":
            result = export_eagle_xml(components, outfile, project_name, company)
        else:
            result = export_generic_netlist(components, outfile, project_name)

        print(f"\nExported {args.export_format} format: {result}")
        print(f"  {len(components)} component(s)")
    else:
        # Default: KiCad schematic output
        if components is not None:
            files = generate_from_components(
                components,
                args.output,
                project_name=project_name,
                company=company,
                stable_uuids=args.stable_uuids,
                validate=args.validate,
                pcb=args.pcb,
                hierarchical=args.hierarchical,
                interface_policy=args.interface_policy,
            )
        elif args.bom:
            files = generate_from_bom(
                args.bom,
                args.output,
                project_name=project_name,
                company=company,
                stable_uuids=args.stable_uuids,
                validate=args.validate,
                pcb=args.pcb,
                hierarchical=args.hierarchical,
                interface_policy=args.interface_policy,
            )
        else:
            files = []

        if files:
            print(f"\nGenerated {len(files)} schematic file(s)")
            print("Open in KiCad: File > Open > select any .kicad_sch")


if __name__ == "__main__":
    main()
