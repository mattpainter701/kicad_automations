"""PCB placement optimizer using simulated annealing.

Multi-objective optimizer that considers thermal, signal integrity,
DFM clearance, and cost constraints. Reads thermal/SI spec data from
Sprint 15's spec harvester output.

Usage:
    from circuit_weaver.placement_optimizer import optimize_placement
    placements = optimize_placement(components, board_width=100, board_height=80)
"""

from __future__ import annotations

import json
import logging
import math
import random
import re
from dataclasses import dataclass, field, replace
from itertools import combinations
from pathlib import Path
from typing import Any

from .component_db import ComponentDef
from .pcb_export import _build_net_component_map

log = logging.getLogger(__name__)

# Footprint size estimates (mm) — width, height
_FOOTPRINT_SIZES: dict[str, tuple[float, float]] = {
    "0201": (0.6, 0.3),
    "0402": (1.0, 0.5),
    "0603": (1.6, 0.8),
    "0805": (2.0, 1.25),
    "1206": (3.2, 1.6),
    "2512": (6.3, 3.2),
    "1210": (3.2, 2.5),
    "SOT-23": (4.0, 3.0),
    "SOT-89": (4.5, 3.5),
    "SOT-223": (6.5, 3.5),
    "SOIC-8": (6.0, 5.0),
    "SOIC-16": (10.0, 6.0),
    "TSSOP-8": (4.4, 3.0),
    "TSSOP-16": (5.0, 4.4),
    "QFN-16": (3.0, 3.0),
    "QFN-20": (4.0, 4.0),
    "QFN-24": (4.0, 4.0),
    "QFN-32": (6.0, 6.0),
    "QFN-48": (7.0, 7.0),
    "LQFP-48": (9.0, 9.0),
    "LQFP-64": (12.0, 12.0),
    "LQFP-100": (16.0, 16.0),
    "BGA-256": (23.0, 23.0),
    "BGA": (15.0, 15.0),
    "ESP32-WROOM": (18.0, 25.5),
    "USB-C": (9.0, 7.5),
}

# Category placement anchors are absolute millimetres from named board edges.
# ``center`` is deliberately explicit; unknown categories use the general anchor
# and never silently acquire digital placement semantics.
_ZONE_ANCHORS: dict[str, tuple[str, float, str, float]] = {
    "power": ("left", 20.0, "top", 22.0),
    "regulator": ("left", 20.0, "top", 22.0),
    "power_management": ("left", 20.0, "top", 22.0),
    "poe": ("left", 20.0, "center", 0.0),
    "motor": ("left", 20.0, "bottom", 20.0),
    "motor_driver": ("left", 20.0, "bottom", 20.0),
    "digital": ("center", 0.0, "center", 0.0),
    "mcu": ("center", 0.0, "center", 0.0),
    "fpga": ("center", 0.0, "center", 0.0),
    "analog": ("center", 0.0, "bottom", 25.0),
    "audio": ("right", 30.0, "bottom", 24.0),
    "audio_amplifier": ("right", 30.0, "bottom", 24.0),
    "comms": ("right", 28.0, "center", 0.0),
    "communication": ("right", 28.0, "center", 0.0),
    "ethernet": ("right", 20.0, "center", 0.0),
    "usb": ("center", 0.0, "bottom", 8.0),
    "rf": ("right", 18.0, "top", 15.0),
    "transceiver": ("right", 28.0, "top", 22.0),
    "clock": ("center", 0.0, "top", 22.0),
    "connector": ("center", 0.0, "bottom", 7.0),
    "debug": ("left", 22.0, "bottom", 8.0),
    "sensor": ("right", 24.0, "bottom", 24.0),
    "sensors": ("right", 24.0, "bottom", 24.0),
    "storage": ("right", 34.0, "center", 0.0),
    "protection": ("left", 9.0, "center", 0.0),
    "passive": ("center", 0.0, "bottom", 18.0),
    "other": ("center", 0.0, "center", 0.0),
}


def _axis_anchor_mm(edge: str, offset_mm: float, extent_mm: float) -> float:
    # Very small auto-sized boards cannot sustain the nominal edge distance.
    # Saturate at 22.5% of the axis while retaining the absolute distance
    # on ordinary boards.
    effective_offset = min(offset_mm, extent_mm * 0.225)
    if edge == "left" or edge == "top":
        return effective_offset
    if edge == "right" or edge == "bottom":
        return extent_mm - effective_offset
    if edge == "center":
        return extent_mm / 2.0
    raise ValueError(f"unknown placement edge {edge!r}")


def _zone_center_mm(category: str, config: PlacementConfig) -> tuple[float, float]:
    anchor = _ZONE_ANCHORS.get(category, _ZONE_ANCHORS["other"])
    return (
        _axis_anchor_mm(anchor[0], anchor[1], config.board_width_mm),
        _axis_anchor_mm(anchor[2], anchor[3], config.board_height_mm),
    )

_PLACEMENT_CONSTRAINT_KINDS = {"placement", "keepout"}
_BOARD_TARGETS = {"board", "board_outline", "pcb", "outline"}
_EDGES = {"left", "right", "top", "bottom"}
_WITHIN_RE = re.compile(
    r"\bwithin\s+(?P<distance>\d+(?:\.\d+)?)\s*mm\s+of\s+(?P<ref>[A-Za-z]+\d+)\b",
    re.IGNORECASE,
)
_EDGE_RE = re.compile(r"\b(left|right|top|bottom)\s+edge\b", re.IGNORECASE)
_FOOTPRINT_DIMENSION_RE = re.compile(
    r"(?<![A-Z0-9.])(\d+(?:\.\d+)?)X(\d+(?:\.\d+)?)MM\b",
    re.IGNORECASE,
)

_GROUND_NET_PREFIXES = ("GND", "AGND", "DGND", "PGND", "VSS", "GNDA", "GNDD")
_POWER_NET_PREFIXES = ("VDD", "VCC", "VBUS", "VIN", "VBAT", "VSYS", "AVDD", "DVDD")
_HIGH_SPEED_NET_TOKENS = (
    "USB",
    "ETH",
    "RGMII",
    "RMII",
    "MII",
    "SPI",
    "QSPI",
    "I2C",
    "UART",
    "CLK",
    "XTAL",
    "SCL",
    "SDA",
    "MOSI",
    "MISO",
    "SCK",
    "TX",
    "RX",
    "DP",
    "DM",
)


@dataclass
class PlacementConfig:
    """Configuration for the placement optimizer."""

    board_width_mm: float = 100.0
    board_height_mm: float = 80.0
    edge_clearance_mm: float = 1.0
    min_component_gap_mm: float = 0.5
    support_body_clearance_mm: float = 1.5
    strategy: str = "balanced"  # simple, thermal, si, cost, balanced
    ambient_temp_c: float = 25.0
    iterations: int = 5000
    initial_temp: float = 100.0
    cooling_rate: float = 0.995
    seed: int | None = None


@dataclass
class ComponentPlacement:
    """Placement state for a single component."""

    ref: str
    x: float
    y: float
    rotation: float = 0.0
    layer: str = "front"
    width: float = 2.0
    height: float = 1.0
    category: str = "other"
    is_power: bool = False
    thermal_dissipation_w: float = 0.0
    requires_impedance_control: bool = False
    parent_ref: str = ""
    placement_role: str = ""
    locked: bool = False
    constraint_locked: bool = False
    geometry_status: str = "estimated"


@dataclass
class _ConstraintPlan:
    """Normalized machine-applicable placement constraints."""

    supplied_count: int = 0
    board_dimension_source: str = "default"
    fixed: dict[str, dict[str, Any]] = field(default_factory=dict)
    edges: dict[str, dict[str, Any]] = field(default_factory=dict)
    affinities: list[dict[str, Any]] = field(default_factory=list)
    keepouts: list[dict[str, Any]] = field(default_factory=list)
    applied: list[dict[str, Any]] = field(default_factory=list)
    deferred: list[dict[str, Any]] = field(default_factory=list)
    unsupported: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def component_part_number(comp: ComponentDef) -> str:
    """Return the original BOM MPN when available, else the registry MPN."""
    return str(comp.source_mpn or comp.mpn or "").strip()


def estimate_footprint_size(footprint: str, reference: str = "") -> tuple[float, float]:
    """Estimate a physical courtyard from one KiCad footprint identifier."""
    fp = str(footprint or "").upper()
    normalized_fp = fp.replace("_", "-")
    for pattern, size in _FOOTPRINT_SIZES.items():
        if pattern.upper() in normalized_fp:
            return size
    dimensions = [
        (float(match.group(1)), float(match.group(2)))
        for match in _FOOTPRINT_DIMENSION_RE.finditer(normalized_fp)
    ]
    if dimensions:
        return max(dimensions, key=lambda size: size[0] * size[1])
    # Default based on category
    if not fp:
        # Missing geometry is rendered as an obvious placeholder and blocked
        # elsewhere; do not let a reference prefix imply physical accuracy.
        return (4.0, 3.0)
    prefix = str(reference or "")[:1].upper()
    if prefix in ("R", "C", "L"):
        return (1.6, 0.8)  # 0603 default
    if prefix == "U":
        return (12.0, 12.0)  # conservative generic IC/courtyard
    if prefix == "J":
        return (8.0, 5.0)  # connector
    return (2.0, 2.0)


def estimate_component_size(comp: ComponentDef) -> tuple[float, float]:
    """Estimate component physical size using the shared footprint model."""
    return estimate_footprint_size(comp.footprint, comp.source_ref)


# Backward-compatible private alias for integrations that imported the old
# helper.  The viewer now consumes the public helper so both use one table.
_estimate_size = estimate_component_size


def _load_thermal_specs(specs_dir: Path | None) -> dict[str, dict]:
    """Load thermal specs from specs/ic_thermal.json if available."""
    if not specs_dir:
        return {}
    path = specs_dir / "ic_thermal.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _load_si_specs(specs_dir: Path | None) -> dict[str, dict]:
    """Load SI specs from specs/si_params.json if available."""
    if not specs_dir:
        return {}
    path = specs_dir / "si_params.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _finite_number(value: Any) -> float | None:
    """Return a finite float for numeric constraint input, else ``None``."""
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _constraint_kind(raw: dict[str, Any]) -> str:
    return str(raw.get("kind") or raw.get("type") or "").strip().lower()


def _constraint_target(raw: dict[str, Any]) -> str:
    return str(raw.get("target") or raw.get("ref") or "").strip()


def _position_values(raw: dict[str, Any]) -> tuple[float | None, float | None]:
    nested = raw.get("position") if isinstance(raw.get("position"), dict) else {}
    x = _finite_number(raw.get("x_mm", raw.get("x", nested.get("x_mm", nested.get("x")))))
    y = _finite_number(raw.get("y_mm", raw.get("y", nested.get("y_mm", nested.get("y")))))
    return x, y


def _derived_review_board(components: list[ComponentDef], config: PlacementConfig) -> tuple[float, float]:
    """Build a compact review canvas when no mechanical outline was supplied."""
    if not components:
        return (30.0, 25.0)
    packing_margin = config.min_component_gap_mm + 0.75
    expanded_area = 0.0
    largest_width = 0.0
    largest_height = 0.0
    for component in components:
        width, height = estimate_component_size(component)
        expanded_area += (width + 2 * packing_margin) * (height + 2 * packing_margin)
        largest_width = max(largest_width, width)
        largest_height = max(largest_height, height)

    # A 32% density leaves room for support rings, routing channels, and
    # interactive edits while avoiding the mostly-empty legacy 100x80 canvas.
    required_area = expanded_area / 0.32
    aspect_ratio = 1.35
    width = math.sqrt(required_area * aspect_ratio)
    height = required_area / width
    width = max(30.0, largest_width + 2 * config.edge_clearance_mm + 8.0, width)
    height = max(25.0, largest_height + 2 * config.edge_clearance_mm + 8.0, height)
    width = min(100.0, math.ceil(width / 5.0) * 5.0)
    height = min(80.0, math.ceil(height / 5.0) * 5.0)
    return (width, height)


def _board_dimensions(
    config: PlacementConfig,
    constraints: list[dict[str, Any]],
    plan: _ConstraintPlan,
) -> PlacementConfig:
    width = float(config.board_width_mm)
    height = float(config.board_height_mm)
    for raw in constraints:
        target = _constraint_target(raw).lower()
        nested = raw.get("board") if isinstance(raw.get("board"), dict) else {}
        explicit_board_keys = "board_width_mm" in raw or "board_height_mm" in raw or bool(nested)
        if target not in _BOARD_TARGETS and not explicit_board_keys:
            continue
        candidate_width = _finite_number(
            raw.get(
                "board_width_mm",
                nested.get("width_mm", raw.get("width_mm") if target in _BOARD_TARGETS else None),
            )
        )
        candidate_height = _finite_number(
            raw.get(
                "board_height_mm",
                nested.get("height_mm", raw.get("height_mm") if target in _BOARD_TARGETS else None),
            )
        )
        if candidate_width is not None:
            width = candidate_width
        if candidate_height is not None:
            height = candidate_height
        if candidate_width is not None or candidate_height is not None:
            plan.board_dimension_source = "constraints"
            plan.applied.append(
                {
                    "kind": "board_outline",
                    "target": target or "board",
                    "width_mm": width,
                    "height_mm": height,
                }
            )

    for name, value in (("board_width_mm", width), ("board_height_mm", height)):
        if not math.isfinite(value) or value <= 0:
            raise ValueError(f"{name} must be a positive finite number")
    if (
        config.edge_clearance_mm < 0
        or config.min_component_gap_mm < 0
        or config.support_body_clearance_mm < 0
    ):
        raise ValueError("Placement clearances must be non-negative")
    return replace(config, board_width_mm=width, board_height_mm=height)


def _normalize_keepout(raw: dict[str, Any], index: int) -> dict[str, Any] | None:
    x = _finite_number(raw.get("x_mm", raw.get("x")))
    y = _finite_number(raw.get("y_mm", raw.get("y")))
    width = _finite_number(raw.get("width_mm", raw.get("width")))
    height = _finite_number(raw.get("height_mm", raw.get("height")))
    x1 = _finite_number(raw.get("x1_mm", raw.get("x1")))
    y1 = _finite_number(raw.get("y1_mm", raw.get("y1")))
    x2 = _finite_number(raw.get("x2_mm", raw.get("x2")))
    y2 = _finite_number(raw.get("y2_mm", raw.get("y2")))
    if None not in (x1, y1, x2, y2):
        left, right = sorted((float(x1), float(x2)))
        top, bottom = sorted((float(y1), float(y2)))
        x, y, width, height = left, top, right - left, bottom - top
    if None in (x, y, width, height) or float(width) <= 0 or float(height) <= 0:
        return None
    return {
        "id": str(raw.get("id") or _constraint_target(raw) or f"keepout_{index + 1}"),
        "x_mm": float(x),
        "y_mm": float(y),
        "width_mm": float(width),
        "height_mm": float(height),
    }


def _build_constraint_plan(
    components: list[ComponentDef],
    config: PlacementConfig,
    constraints: list[dict[str, Any]] | None,
) -> tuple[PlacementConfig, _ConstraintPlan]:
    """Normalize the documented placement subset and expose everything else."""
    raw_constraints = [item for item in (constraints or []) if isinstance(item, dict)]
    plan = _ConstraintPlan(supplied_count=len(raw_constraints))
    if (config.board_width_mm, config.board_height_mm) != (100.0, 80.0):
        plan.board_dimension_source = "config"
    else:
        derived_width, derived_height = _derived_review_board(components, config)
        config = replace(
            config,
            board_width_mm=derived_width,
            board_height_mm=derived_height,
        )
        plan.board_dimension_source = "derived_review"
    effective_config = _board_dimensions(config, raw_constraints, plan)
    refs = {str(comp.source_ref or "").strip() for comp in components if comp.source_ref}

    for index, raw in enumerate(raw_constraints):
        kind = _constraint_kind(raw)
        target = _constraint_target(raw)
        target_lower = target.lower()
        if kind not in _PLACEMENT_CONSTRAINT_KINDS:
            plan.deferred.append(
                {
                    "index": index,
                    "kind": kind or "unspecified",
                    "target": target,
                    "reason": "Constraint belongs to a non-placement stage.",
                }
            )
            continue

        has_board_keys = (
            target_lower in _BOARD_TARGETS
            or "board_width_mm" in raw
            or "board_height_mm" in raw
            or isinstance(raw.get("board"), dict)
        )
        if kind == "placement" and has_board_keys:
            # Already recorded by _board_dimensions. A board entry may also
            # carry clearance policy, which is applied below.
            edge_clearance = _finite_number(raw.get("edge_clearance_mm"))
            min_gap = _finite_number(raw.get("min_component_gap_mm"))
            if edge_clearance is not None or min_gap is not None:
                if edge_clearance is not None and edge_clearance < 0:
                    raise ValueError("edge_clearance_mm must be non-negative")
                if min_gap is not None and min_gap < 0:
                    raise ValueError("min_component_gap_mm must be non-negative")
                effective_config = replace(
                    effective_config,
                    edge_clearance_mm=(
                        edge_clearance
                        if edge_clearance is not None
                        else effective_config.edge_clearance_mm
                    ),
                    min_component_gap_mm=(
                        min_gap if min_gap is not None else effective_config.min_component_gap_mm
                    ),
                )
                plan.applied.append(
                    {
                        "kind": "board_clearance",
                        "target": target or "board",
                        "edge_clearance_mm": effective_config.edge_clearance_mm,
                        "min_component_gap_mm": effective_config.min_component_gap_mm,
                    }
                )
            continue

        if kind == "keepout":
            keepout = _normalize_keepout(raw, index)
            if keepout is None:
                plan.unsupported.append(
                    {
                        "index": index,
                        "kind": kind,
                        "target": target,
                        "reason": "Rectangular keepout requires x/y/width/height (mm).",
                    }
                )
            else:
                plan.keepouts.append(keepout)
                plan.applied.append({"kind": "keepout", "target": target, **keepout})
            continue

        if not target or target not in refs:
            plan.unsupported.append(
                {
                    "index": index,
                    "kind": kind,
                    "target": target,
                    "reason": "Placement target is missing from the assembly inventory.",
                }
            )
            continue

        description = str(raw.get("constraint") or raw.get("description") or "")
        x, y = _position_values(raw)
        rotation = _finite_number(raw.get("rotation"))
        layer = str(raw.get("layer") or "front").lower()
        if x is not None and y is not None:
            if layer not in {"front", "back"}:
                plan.unsupported.append(
                    {
                        "index": index,
                        "kind": kind,
                        "target": target,
                        "reason": "Fixed placement layer must be 'front' or 'back'.",
                    }
                )
                continue
            fixed = {
                "x_mm": x,
                "y_mm": y,
                "rotation": (rotation or 0.0) % 360,
                "layer": layer,
            }
            if target in plan.fixed:
                plan.warnings.append(f"Later fixed placement replaced an earlier constraint for {target}.")
            plan.fixed[target] = fixed
            plan.applied.append({"kind": "fixed_position", "target": target, **fixed})
            continue

        edge = str(raw.get("edge") or "").lower()
        edge_match = _EDGE_RE.search(description)
        if not edge and edge_match:
            edge = edge_match.group(1).lower()
        if edge in _EDGES:
            tolerance = _finite_number(raw.get("max_distance_mm", raw.get("tolerance_mm", 1.0)))
            plan.edges[target] = {"edge": edge, "max_distance_mm": max(0.0, tolerance or 0.0)}
            plan.applied.append({"kind": "edge", "target": target, **plan.edges[target]})
            continue

        near = str(raw.get("near") or raw.get("near_ref") or "").strip()
        max_distance = _finite_number(raw.get("max_distance_mm", raw.get("distance_mm")))
        within_match = _WITHIN_RE.search(description)
        if within_match and "pin" in description.lower() and not near:
            plan.unsupported.append(
                {
                    "index": index,
                    "kind": kind,
                    "target": target,
                    "reason": (
                        "Pin-relative placement requires resolved footprint pad coordinates; "
                        "the component-center optimizer cannot apply it safely."
                    ),
                }
            )
            continue
        if within_match:
            near = near or within_match.group("ref")
            max_distance = max_distance or float(within_match.group("distance"))
        if near and max_distance is not None and max_distance >= 0 and near in refs:
            affinity = {"target": target, "near": near, "max_distance_mm": max_distance}
            plan.affinities.append(affinity)
            plan.applied.append({"kind": "affinity", **affinity})
            continue

        plan.unsupported.append(
            {
                "index": index,
                "kind": kind,
                "target": target,
                "reason": (
                    "Placement constraint needs fixed x/y, a named edge, or near/max_distance_mm."
                ),
            }
        )

    return effective_config, plan


def _init_placements(
    components: list[ComponentDef],
    config: PlacementConfig,
    thermal_specs: dict[str, dict],
    si_specs: dict[str, dict],
    constraint_plan: _ConstraintPlan | None = None,
) -> list[ComponentPlacement]:
    """Create initial placement state with zone-based positions."""
    placements: list[ComponentPlacement] = []
    placement_by_ref: dict[str, ComponentPlacement] = {}
    zone_counters: dict[str, int] = {}
    support_counters: dict[str, int] = {}

    # Owners must be placed before generated support parts so bypass,
    # bootstrap, feedback, and strap parts start next to the correct IC.
    ordered = sorted(
        enumerate(components),
        key=lambda item: (bool(getattr(item[1], "placement_parent_ref", "")), item[0]),
    )

    for _original_index, comp in ordered:
        if not comp.source_ref:
            continue

        w, h = estimate_component_size(comp)
        cat = (comp.category or "other").lower()
        if cat not in _ZONE_ANCHORS:
            cat = "passive" if comp.source_ref[0] in "RCL" else "other"
        parent_ref = str(getattr(comp, "placement_parent_ref", "") or "")
        placement_role = str(getattr(comp, "placement_role", "") or "")
        parent = placement_by_ref.get(parent_ref)

        if parent is not None:
            support_idx = support_counters.get(parent_ref, 0)
            support_counters[parent_ref] = support_idx + 1
            # Walk clockwise around the owner. The first support part lands
            # on the owner's power-entry side; later parts fan out in a tight
            # ring instead of falling into a board-wide passive bank.
            offsets = ((-1, 0), (0, -1), (1, 0), (0, 1), (-1, -1), (1, -1), (1, 1), (-1, 1))
            ox, oy = offsets[support_idx % len(offsets)]
            ring = support_idx // len(offsets)
            radius_x = parent.width / 2 + w / 2 + config.min_component_gap_mm + 0.6 + ring * (w + 0.6)
            radius_y = parent.height / 2 + h / 2 + config.min_component_gap_mm + 0.6 + ring * (h + 0.6)
            x = parent.x + ox * radius_x
            y = parent.y + oy * radius_y
        else:
            zone_cx, zone_cy = _zone_center_mm(cat, config)

            idx = zone_counters.get(cat, 0)
            zone_counters[cat] = idx + 1
            cols = max(1, int(math.sqrt(idx + 1)))
            row, col = divmod(idx, cols)
            offset_x = col * (w + config.min_component_gap_mm + 1.0)
            offset_y = row * (h + config.min_component_gap_mm + 1.0)
            x = zone_cx + offset_x
            y = zone_cy + offset_y

        x = max(
            config.edge_clearance_mm + w / 2,
            min(x, config.board_width_mm - config.edge_clearance_mm - w / 2),
        )
        y = max(
            config.edge_clearance_mm + h / 2,
            min(y, config.board_height_mm - config.edge_clearance_mm - h / 2),
        )

        fixed = (constraint_plan.fixed if constraint_plan else {}).get(comp.source_ref)
        edge_constraint = (constraint_plan.edges if constraint_plan else {}).get(comp.source_ref)
        rotation = float(fixed.get("rotation", 0.0)) if fixed else 0.0
        layer = str(fixed.get("layer", "front")) if fixed else "front"
        effective_w, effective_h = (h, w) if int(round(rotation)) % 180 == 90 else (w, h)
        if edge_constraint:
            edge = edge_constraint["edge"]
            if edge == "left":
                x = config.edge_clearance_mm + effective_w / 2
            elif edge == "right":
                x = config.board_width_mm - config.edge_clearance_mm - effective_w / 2
            elif edge == "top":
                y = config.edge_clearance_mm + effective_h / 2
            elif edge == "bottom":
                y = config.board_height_mm - config.edge_clearance_mm - effective_h / 2
        if fixed:
            x = float(fixed["x_mm"])
            y = float(fixed["y_mm"])

        mpn = component_part_number(comp)
        thermal = thermal_specs.get(mpn, {})
        si = si_specs.get(mpn, {})

        placement = ComponentPlacement(
            ref=comp.source_ref,
            x=x,
            y=y,
            rotation=rotation,
            layer=layer,
            width=w,
            height=h,
            category=cat,
            is_power=cat in {"power", "regulator", "poe"},
            thermal_dissipation_w=thermal.get("pdiss_max_w", 0.0)
            if isinstance(thermal.get("pdiss_max_w"), (int, float))
            else 0.0,
            requires_impedance_control=si.get("requires_impedance_control", False),
            parent_ref=parent_ref,
            placement_role=placement_role,
            locked=bool(fixed),
            constraint_locked=bool(fixed),
            geometry_status=str(
                getattr(comp, "placement_geometry_status", "estimated") or "estimated"
            ),
        )
        placements.append(placement)
        placement_by_ref[placement.ref] = placement

    return placements


def _overlap_area(a: ComponentPlacement, b: ComponentPlacement, gap: float = 0.0) -> float:
    """Calculate overlap area between two components (including gap)."""
    aw, ah = _effective_dimensions(a)
    bw, bh = _effective_dimensions(b)
    ax1, ay1 = a.x - aw / 2 - gap, a.y - ah / 2 - gap
    ax2, ay2 = a.x + aw / 2 + gap, a.y + ah / 2 + gap
    bx1, by1 = b.x - bw / 2 - gap, b.y - bh / 2 - gap
    bx2, by2 = b.x + bw / 2 + gap, b.y + bh / 2 + gap

    dx = min(ax2, bx2) - max(ax1, bx1)
    dy = min(ay2, by2) - max(ay1, by1)
    if dx > 0 and dy > 0:
        return dx * dy
    return 0.0


def _effective_dimensions(placement: ComponentPlacement) -> tuple[float, float]:
    """Return the axis-aligned footprint extent after orthogonal rotation."""
    rotation = int(round(placement.rotation)) % 180
    return (
        (placement.height, placement.width)
        if rotation == 90
        else (placement.width, placement.height)
    )


def _rectangle_clearance(a: ComponentPlacement, b: ComponentPlacement) -> float:
    """Return edge-to-edge clearance between rotated rectangular courtyards."""
    aw, ah = _effective_dimensions(a)
    bw, bh = _effective_dimensions(b)
    dx = max(0.0, abs(a.x - b.x) - (aw + bw) / 2)
    dy = max(0.0, abs(a.y - b.y) - (ah + bh) / 2)
    return math.hypot(dx, dy)


def _is_parent_support_pair(a: ComponentPlacement, b: ComponentPlacement) -> bool:
    return a.parent_ref == b.ref or b.parent_ref == a.ref


def _intersects_keepout(placement: ComponentPlacement, keepout: dict[str, Any]) -> bool:
    width, height = _effective_dimensions(placement)
    left = placement.x - width / 2
    right = placement.x + width / 2
    top = placement.y - height / 2
    bottom = placement.y + height / 2
    keepout_left = float(keepout["x_mm"])
    keepout_top = float(keepout["y_mm"])
    keepout_right = keepout_left + float(keepout["width_mm"])
    keepout_bottom = keepout_top + float(keepout["height_mm"])
    return (
        right > keepout_left
        and left < keepout_right
        and bottom > keepout_top
        and top < keepout_bottom
    )


def _cost_overlap(placements: list[ComponentPlacement], gap: float) -> float:
    """Penalty for overlapping components."""
    total = 0.0
    for i in range(len(placements)):
        for j in range(i + 1, len(placements)):
            total += _overlap_area(placements[i], placements[j], gap)
    return total * 1000.0  # Heavy penalty


def _cost_support_body_clearance(
    placements: list[ComponentPlacement], config: PlacementConfig
) -> float:
    by_ref = {placement.ref: placement for placement in placements}
    total = 0.0
    for support in placements:
        if not support.parent_ref:
            continue
        parent = by_ref.get(support.parent_ref)
        if parent is None:
            continue
        clearance = _rectangle_clearance(support, parent)
        if clearance < config.support_body_clearance_mm:
            total += (config.support_body_clearance_mm - clearance) ** 2 * 10_000.0
    return total


def _cost_keepouts(
    placements: list[ComponentPlacement], constraint_plan: _ConstraintPlan | None
) -> float:
    if not constraint_plan or not constraint_plan.keepouts:
        return 0.0
    return 100_000.0 * sum(
        1
        for placement in placements
        for keepout in constraint_plan.keepouts
        if _intersects_keepout(placement, keepout)
    )


def _cost_boundary(placements: list[ComponentPlacement], config: PlacementConfig) -> float:
    """Penalty for components outside board boundary."""
    total = 0.0
    for p in placements:
        margin = config.edge_clearance_mm
        width, height = _effective_dimensions(p)
        if p.x - width / 2 < margin:
            total += (margin - (p.x - width / 2)) ** 2
        if p.x + width / 2 > config.board_width_mm - margin:
            total += ((p.x + width / 2) - (config.board_width_mm - margin)) ** 2
        if p.y - height / 2 < margin:
            total += (margin - (p.y - height / 2)) ** 2
        if p.y + height / 2 > config.board_height_mm - margin:
            total += ((p.y + height / 2) - (config.board_height_mm - margin)) ** 2
    return total * 500.0


def _cost_thermal(placements: list[ComponentPlacement]) -> float:
    """Penalty for hot components placed too close together."""
    total = 0.0
    hot = [p for p in placements if p.thermal_dissipation_w > 0.1]
    for i in range(len(hot)):
        for j in range(i + 1, len(hot)):
            dist = math.hypot(hot[i].x - hot[j].x, hot[i].y - hot[j].y)
            combined_heat = hot[i].thermal_dissipation_w + hot[j].thermal_dissipation_w
            if dist < 15.0:  # Within 15mm
                total += combined_heat * (15.0 - dist)
    return total * 10.0


def _cost_zone(placements: list[ComponentPlacement], config: PlacementConfig) -> float:
    """Penalty for components far from their preferred zone."""
    total = 0.0
    for p in placements:
        ideal_x, ideal_y = _zone_center_mm(p.category, config)
        dist = math.hypot(p.x - ideal_x, p.y - ideal_y)
        total += dist * 0.1
    return total


def _net_weight(net_name: str) -> float:
    upper = (net_name or "").upper()
    if not upper or upper.startswith(_GROUND_NET_PREFIXES):
        return 0.0
    if upper.startswith(_POWER_NET_PREFIXES):
        return 0.5
    if any(token in upper for token in _HIGH_SPEED_NET_TOKENS):
        return 3.0
    return 1.0


def _build_connectivity_pairs(components: list[ComponentDef]) -> dict[tuple[str, str], float]:
    """Collapse shared nets into weighted functional-block attractions.

    Generated passives inherit their owner's identity here. Treating every
    decoupler on a power rail as an independent graph vertex creates a dense
    all-to-all clique that overwhelms useful block-to-block connectivity.
    """
    pair_weights: dict[tuple[str, str], float] = {}
    owner_by_ref = {
        str(component.source_ref): str(
            getattr(component, "placement_parent_ref", "") or component.source_ref
        )
        for component in components
        if component.source_ref
    }
    for net_name, refs in _build_net_component_map(components).items():
        block_refs = sorted({owner_by_ref.get(ref, ref) for ref in refs})
        if len(block_refs) < 2:
            continue
        weight = _net_weight(net_name)
        if weight <= 0:
            continue
        for a, b in combinations(block_refs, 2):
            key = tuple(sorted((a, b)))
            pair_weights[key] = pair_weights.get(key, 0.0) + weight
    return pair_weights


def _cost_connectivity(
    placements: list[ComponentPlacement],
    connectivity_pairs: dict[tuple[str, str], float],
) -> float:
    """Penalty for placing connected components far apart."""
    if not connectivity_pairs:
        return 0.0
    placement_by_ref = {p.ref: p for p in placements}
    total = 0.0
    for (ref_a, ref_b), weight in connectivity_pairs.items():
        a = placement_by_ref.get(ref_a)
        b = placement_by_ref.get(ref_b)
        if a is None or b is None:
            continue
        dx = a.x - b.x
        dy = a.y - b.y
        total += (dx * dx + dy * dy) * weight
    return total * 0.2


def _cost_parent_affinity(placements: list[ComponentPlacement]) -> float:
    """Keep generated support parts close to the IC they electrically serve."""
    by_ref = {placement.ref: placement for placement in placements}
    total = 0.0
    for placement in placements:
        if not placement.parent_ref:
            continue
        parent = by_ref.get(placement.parent_ref)
        if parent is None:
            total += 10_000.0
            continue
        distance = math.hypot(placement.x - parent.x, placement.y - parent.y)
        critical = placement.placement_role in {"decoupling", "bootstrap", "feedback", "crystal_load"}
        preferred = 4.0 if critical else 8.0
        weight = 35.0 if critical else 12.0
        total += distance * weight
        if distance > preferred:
            total += (distance - preferred) ** 2 * weight * 5.0
    return total


def _cost_edge_affinity(placements: list[ComponentPlacement], config: PlacementConfig) -> float:
    """Penalize externally accessible and antenna parts placed deep inside the board."""
    total = 0.0
    for placement in placements:
        if placement.category not in {"connector", "usb", "debug", "rf"}:
            continue
        distances = (
            placement.x - placement.width / 2,
            config.board_width_mm - (placement.x + placement.width / 2),
            placement.y - placement.height / 2,
            config.board_height_mm - (placement.y + placement.height / 2),
        )
        nearest_edge = max(0.0, min(distances))
        target = config.edge_clearance_mm + (3.0 if placement.category == "rf" else 1.0)
        if nearest_edge > target:
            total += (nearest_edge - target) ** 2 * (20.0 if placement.category == "rf" else 8.0)
    return total


def _cost_noise_separation(placements: list[ComponentPlacement]) -> float:
    """Keep RF/clock/analog circuitry away from switching power blocks."""
    noisy = [p for p in placements if p.category in {"power", "regulator", "poe"} and not p.parent_ref]
    sensitive = [
        p
        for p in placements
        if p.category in {"rf", "clock", "analog", "sensor", "sensors"} and not p.parent_ref
    ]
    total = 0.0
    for source in noisy:
        for victim in sensitive:
            distance = math.hypot(source.x - victim.x, source.y - victim.y)
            if distance < 12.0:
                total += (12.0 - distance) ** 2 * 8.0
    return total


def _cost_compactness(
    placements: list[ComponentPlacement], config: PlacementConfig
) -> float:
    """Discourage sparse island placement when connectivity data is incomplete."""
    internal = [
        placement
        for placement in placements
        if placement.category not in {"connector", "usb", "debug", "rf"}
        and not placement.parent_ref
        and not placement.constraint_locked
    ]
    if len(internal) < 2:
        return 0.0
    center_x = sum(placement.x for placement in internal) / len(internal)
    center_y = sum(placement.y for placement in internal) / len(internal)
    radial = sum(
        math.hypot(placement.x - center_x, placement.y - center_y) for placement in internal
    )
    min_x = min(placement.x for placement in internal)
    max_x = max(placement.x for placement in internal)
    min_y = min(placement.y for placement in internal)
    max_y = max(placement.y for placement in internal)
    content_center_x = (min_x + max_x) / 2
    content_center_y = (min_y + max_y) / 2
    board_center_x = config.board_width_mm / 2
    board_center_y = config.board_height_mm / 2
    centering = (content_center_x - board_center_x) ** 2 + (
        content_center_y - board_center_y
    ) ** 2
    return radial * 2.5 + (max_x - min_x) * (max_y - min_y) * 0.4 + centering * 20.0


def _distance_to_edge(
    placement: ComponentPlacement, edge: str, config: PlacementConfig
) -> float:
    width, height = _effective_dimensions(placement)
    if edge == "left":
        return placement.x - width / 2 - config.edge_clearance_mm
    if edge == "right":
        return config.board_width_mm - config.edge_clearance_mm - (placement.x + width / 2)
    if edge == "top":
        return placement.y - height / 2 - config.edge_clearance_mm
    return config.board_height_mm - config.edge_clearance_mm - (placement.y + height / 2)


def _cost_supplied_constraints(
    placements: list[ComponentPlacement],
    config: PlacementConfig,
    constraint_plan: _ConstraintPlan | None,
) -> float:
    if not constraint_plan:
        return 0.0
    by_ref = {placement.ref: placement for placement in placements}
    total = _cost_keepouts(placements, constraint_plan)
    for ref, edge_rule in constraint_plan.edges.items():
        placement = by_ref.get(ref)
        if placement is None:
            continue
        distance = max(0.0, _distance_to_edge(placement, edge_rule["edge"], config))
        total += distance * distance * 2_000.0
    for affinity in constraint_plan.affinities:
        target = by_ref.get(affinity["target"])
        neighbor = by_ref.get(affinity["near"])
        if target is None or neighbor is None:
            continue
        distance = math.hypot(target.x - neighbor.x, target.y - neighbor.y)
        maximum = float(affinity["max_distance_mm"])
        if distance > maximum:
            total += (distance - maximum) ** 2 * 5_000.0
    return total


def _total_cost(
    placements: list[ComponentPlacement],
    config: PlacementConfig,
    connectivity_pairs: dict[tuple[str, str], float] | None = None,
    constraint_plan: _ConstraintPlan | None = None,
) -> float:
    """Compute total placement cost based on strategy."""
    cost = _cost_overlap(placements, config.min_component_gap_mm)
    cost += _cost_boundary(placements, config)
    cost += _cost_parent_affinity(placements)
    cost += _cost_support_body_clearance(placements, config)
    cost += _cost_edge_affinity(placements, config)
    cost += _cost_supplied_constraints(placements, config, constraint_plan)

    if config.strategy in ("thermal", "balanced"):
        cost += _cost_thermal(placements)
    if config.strategy in ("si", "balanced"):
        cost += _cost_connectivity(placements, connectivity_pairs or {})
        cost += _cost_noise_separation(placements)
    if config.strategy in ("cost", "balanced"):
        cost += _cost_zone(placements, config)
        cost += _cost_compactness(placements, config)

    return cost


def _perturb(
    placements: list[ComponentPlacement], config: PlacementConfig, rng: random.Random
) -> list[ComponentPlacement]:
    """Create a neighbor solution by moving one component."""
    new = [ComponentPlacement(**p.__dict__) for p in placements]
    movable = [index for index, placement in enumerate(new) if not placement.constraint_locked]
    if not movable:
        return new
    idx = rng.choice(movable)
    p = new[idx]

    move_type = rng.random()
    if move_type < 0.22:
        # Translate an electrical block as a unit. Moving only an owner first
        # creates a large parent-affinity barrier, which previously trapped
        # complete power/sensor islands in their initial corner zones.
        root_ref = p.parent_ref or p.ref
        root = next((placement for placement in new if placement.ref == root_ref), None)
        group = (
            []
            if root is not None and root.constraint_locked
            else [
                placement
                for placement in new
                if (placement.ref == root_ref or placement.parent_ref == root_ref)
                and not placement.constraint_locked
            ]
        )
        if group:
            dx = rng.gauss(0, 8.0)
            dy = rng.gauss(0, 8.0)
            margin = config.edge_clearance_mm
            minimum_dx = max(
                margin + _effective_dimensions(item)[0] / 2 - item.x for item in group
            )
            maximum_dx = min(
                config.board_width_mm - margin - _effective_dimensions(item)[0] / 2 - item.x
                for item in group
            )
            minimum_dy = max(
                margin + _effective_dimensions(item)[1] / 2 - item.y for item in group
            )
            maximum_dy = min(
                config.board_height_mm - margin - _effective_dimensions(item)[1] / 2 - item.y
                for item in group
            )
            dx = max(minimum_dx, min(dx, maximum_dx))
            dy = max(minimum_dy, min(dy, maximum_dy))
            for item in group:
                item.x += dx
                item.y += dy
            return new
    if move_type < 0.55:
        # Small move
        p.x += rng.gauss(0, 2.0)
        p.y += rng.gauss(0, 2.0)
    elif move_type < 0.75:
        # Occasional broad moves let sparse zone seeds converge on a compact
        # layout instead of remaining isolated across a large default canvas.
        p.x += rng.gauss(0, 8.0)
        p.y += rng.gauss(0, 8.0)
    elif move_type < 0.9 and len(movable) > 1:
        # Swap two components
        compatible = [
            index
            for index in movable
            if bool(new[index].parent_ref) == bool(p.parent_ref)
        ]
        other = rng.choice(compatible)
        if other != idx:
            new[idx].x, new[other].x = new[other].x, new[idx].x
            new[idx].y, new[other].y = new[other].y, new[idx].y
    else:
        # Rotate
        p.rotation = rng.choice([0, 90, 180, 270])

    # Clamp to board using the rotated footprint extent.
    margin = config.edge_clearance_mm
    width, height = _effective_dimensions(p)
    p.x = max(margin + width / 2, min(p.x, config.board_width_mm - margin - width / 2))
    p.y = max(margin + height / 2, min(p.y, config.board_height_mm - margin - height / 2))

    return new


def _inside_board(
    placement: ComponentPlacement,
    config: PlacementConfig,
    constraint_plan: _ConstraintPlan | None = None,
) -> bool:
    width, height = _effective_dimensions(placement)
    margin = config.edge_clearance_mm
    inside = (
        placement.x - width / 2 >= margin
        and placement.x + width / 2 <= config.board_width_mm - margin
        and placement.y - height / 2 >= margin
        and placement.y + height / 2 <= config.board_height_mm - margin
    )
    return inside and not any(
        _intersects_keepout(placement, keepout)
        for keepout in (constraint_plan.keepouts if constraint_plan else [])
    )


def _legalize_overlaps(
    state: list[ComponentPlacement],
    config: PlacementConfig,
    constraint_plan: _ConstraintPlan | None = None,
) -> tuple[list[ComponentPlacement], int]:
    """Deterministically move colliding parts to the nearest free location.

    Simulated annealing is a proposal engine, not a packing guarantee.  This
    final legalization pass processes owners before their support parts and
    searches an expanding 0.5 mm grid, preventing a visually plausible result
    from still containing physically overlapping courtyards.
    """
    legalized: list[ComponentPlacement] = []
    moved = 0
    step = max(0.5, min(config.min_component_gap_mm, 1.0))
    max_ring = int(math.ceil(max(config.board_width_mm, config.board_height_mm) / step))

    ordered = [
        placement
        for _index, placement in sorted(
            enumerate(state),
            key=lambda item: (
                bool(item[1].parent_ref),
                not item[1].constraint_locked,
                item[0],
            ),
        )
    ]
    for original in ordered:
        placement = ComponentPlacement(**original.__dict__)
        desired_x, desired_y = placement.x, placement.y

        def is_free() -> bool:
            if not _inside_board(placement, config, constraint_plan):
                return False
            for other in legalized:
                if _overlap_area(placement, other, config.min_component_gap_mm) > 0:
                    return False
                if (
                    _is_parent_support_pair(placement, other)
                    and _rectangle_clearance(placement, other)
                    < config.support_body_clearance_mm
                ):
                    return False
            return True

        # Machine-fixed positions are preserved exactly. Any impossible or
        # colliding fixed constraint is surfaced in the result violations.
        if placement.constraint_locked:
            legalized.append(placement)
            continue
        if not is_free():
            found = False
            seen: set[tuple[float, float]] = set()
            for ring in range(1, max_ring + 1):
                offsets: list[tuple[int, int]] = []
                for delta in range(-ring, ring + 1):
                    offsets.extend(
                        ((delta, -ring), (delta, ring), (-ring, delta), (ring, delta))
                    )
                offsets = sorted(
                    set(offsets),
                    key=lambda value: (value[0] ** 2 + value[1] ** 2, value[1], value[0]),
                )
                for dx, dy in offsets:
                    candidate = (round(desired_x + dx * step, 3), round(desired_y + dy * step, 3))
                    if candidate in seen:
                        continue
                    seen.add(candidate)
                    placement.x, placement.y = candidate
                    if is_free():
                        found = True
                        break
                if found:
                    break
            if found:
                moved += 1
            else:
                placement.x, placement.y = desired_x, desired_y
        legalized.append(placement)

    return legalized, moved


def _constraint_evaluation(
    state: list[ComponentPlacement],
    config: PlacementConfig,
    plan: _ConstraintPlan,
) -> dict[str, Any]:
    by_ref = {placement.ref: placement for placement in state}
    violations: list[dict[str, Any]] = []
    for ref, fixed in sorted(plan.fixed.items()):
        placement = by_ref.get(ref)
        if placement is None:
            continue
        if not _inside_board(placement, config):
            violations.append(
                {"kind": "fixed_position", "target": ref, "reason": "Fixed footprint is outside the board."}
            )
        if any(_intersects_keepout(placement, keepout) for keepout in plan.keepouts):
            violations.append(
                {"kind": "fixed_position", "target": ref, "reason": "Fixed footprint intersects a keepout."}
            )
        if (
            abs(placement.x - float(fixed["x_mm"])) > 0.001
            or abs(placement.y - float(fixed["y_mm"])) > 0.001
        ):
            violations.append(
                {"kind": "fixed_position", "target": ref, "reason": "Fixed coordinate was not preserved."}
            )

    for ref, edge_rule in sorted(plan.edges.items()):
        placement = by_ref.get(ref)
        if placement is None:
            continue
        distance = max(0.0, _distance_to_edge(placement, edge_rule["edge"], config))
        if distance > float(edge_rule["max_distance_mm"]) + 0.001:
            violations.append(
                {
                    "kind": "edge",
                    "target": ref,
                    "reason": f"Footprint is {distance:.2f} mm from the requested {edge_rule['edge']} edge.",
                }
            )

    for affinity in plan.affinities:
        target = by_ref.get(affinity["target"])
        neighbor = by_ref.get(affinity["near"])
        if target is None or neighbor is None:
            continue
        distance = math.hypot(target.x - neighbor.x, target.y - neighbor.y)
        maximum = float(affinity["max_distance_mm"])
        if distance > maximum + 0.001:
            violations.append(
                {
                    "kind": "affinity",
                    "target": affinity["target"],
                    "reason": (
                        f"Center is {distance:.2f} mm from {affinity['near']} "
                        f"(maximum {maximum:.2f} mm)."
                    ),
                }
            )

    for placement in state:
        for keepout in plan.keepouts:
            if _intersects_keepout(placement, keepout):
                violations.append(
                    {
                        "kind": "keepout",
                        "target": placement.ref,
                        "reason": f"Footprint intersects keepout {keepout['id']}.",
                    }
                )

    return {
        "supplied_count": plan.supplied_count,
        "board_dimension_source": plan.board_dimension_source,
        "effective_board": {
            "width_mm": config.board_width_mm,
            "height_mm": config.board_height_mm,
            "edge_clearance_mm": config.edge_clearance_mm,
            "min_component_gap_mm": config.min_component_gap_mm,
            "dimensions_verified": plan.board_dimension_source in {"config", "constraints"},
        },
        "applied_count": len(plan.applied),
        "applied": plan.applied,
        "deferred": plan.deferred,
        "unsupported": plan.unsupported,
        "warnings": plan.warnings,
        "keepouts": plan.keepouts,
        "violations": violations,
        "all_placement_constraints_applied": not plan.unsupported,
        "all_applied_constraints_satisfied": not violations,
    }


def optimize_placement(
    components: list[ComponentDef],
    *,
    config: PlacementConfig | None = None,
    specs_dir: str | Path | None = None,
    constraints: list[dict[str, Any]] | None = None,
) -> dict:
    """Run simulated annealing placement optimizer.

    Args:
        components: List of ComponentDef from compiled design.
        config: Optimizer configuration (defaults to balanced strategy).
        specs_dir: Path to specs/ directory with thermal/SI JSON files.
        constraints: Machine-readable placement/keepout constraints. Routing
            constraints are reported as deferred and never claimed as applied.

    Returns:
        {
            "status": "ok",
            "placements": {ref: {x, y, rotation, layer}},
            "board_width_mm": float,
            "board_height_mm": float,
            "iterations": int,
            "final_cost": float,
            "initial_cost": float,
            "strategy": str,
            "thermal_warnings": [...],
        }
    """
    if config is None:
        config = PlacementConfig()
    config, constraint_plan = _build_constraint_plan(components, config, constraints)

    specs_path = Path(specs_dir) if specs_dir else None
    thermal_specs = _load_thermal_specs(specs_path)
    si_specs = _load_si_specs(specs_path)
    connectivity_pairs = _build_connectivity_pairs(components)

    state = _init_placements(components, config, thermal_specs, si_specs, constraint_plan)

    if not state:
        constraint_evaluation = _constraint_evaluation(state, config, constraint_plan)
        return {
            "status": "ok",
            "placements": {},
            "board_width_mm": config.board_width_mm,
            "board_height_mm": config.board_height_mm,
            "iterations": 0,
            "final_cost": 0.0,
            "initial_cost": 0.0,
            "strategy": config.strategy,
            "thermal_warnings": [],
            "constraint_evaluation": constraint_evaluation,
            "quality": {
                "overlaps": [],
                "outside_board": [],
                "missing_parents": [],
                "support_body_violations": [],
                "max_support_distance_mm": 0.0,
                "legalization_moves": 0,
                "review_required": bool(
                    constraint_evaluation["unsupported"] or constraint_evaluation["violations"]
                ),
            },
        }

    if config.strategy == "simple":
        # Skip optimization, return initial zone-based placement
        legalized, moved = _legalize_overlaps(state, config, constraint_plan)
        return _build_result(
            legalized,
            config,
            0,
            0.0,
            0.0,
            legalization_moves=moved,
            constraint_plan=constraint_plan,
        )

    rng = random.Random(config.seed)
    current_cost = _total_cost(state, config, connectivity_pairs, constraint_plan)
    initial_cost = current_cost
    best_state = state
    best_cost = current_cost
    temp = config.initial_temp

    for i in range(config.iterations):
        candidate = _perturb(state, config, rng)
        candidate_cost = _total_cost(candidate, config, connectivity_pairs, constraint_plan)
        delta = candidate_cost - current_cost

        if delta < 0 or rng.random() < math.exp(-delta / max(temp, 0.001)):
            state = candidate
            current_cost = candidate_cost
            if current_cost < best_cost:
                best_state = state
                best_cost = current_cost

        temp *= config.cooling_rate

    legalized, moved = _legalize_overlaps(best_state, config, constraint_plan)
    legalized_cost = _total_cost(legalized, config, connectivity_pairs, constraint_plan)
    return _build_result(
        legalized,
        config,
        config.iterations,
        initial_cost,
        legalized_cost,
        legalization_moves=moved,
        constraint_plan=constraint_plan,
    )


def _build_result(
    state: list[ComponentPlacement],
    config: PlacementConfig,
    iterations: int,
    initial_cost: float,
    final_cost: float,
    *,
    legalization_moves: int = 0,
    constraint_plan: _ConstraintPlan | None = None,
) -> dict:
    """Build the result dict from optimizer state."""
    placements = {}
    thermal_warnings = []
    overlap_pairs: list[list[str]] = []
    outside_board: list[str] = []
    missing_parents: list[str] = []
    support_body_violations: list[dict[str, Any]] = []
    support_distances: list[float] = []
    by_ref = {placement.ref: placement for placement in state}

    for idx, first in enumerate(state):
        for second in state[idx + 1 :]:
            if _overlap_area(first, second, config.min_component_gap_mm) > 0:
                overlap_pairs.append([first.ref, second.ref])
        if first.parent_ref:
            parent = by_ref.get(first.parent_ref)
            if parent is None:
                missing_parents.append(first.ref)
            else:
                support_distances.append(math.hypot(first.x - parent.x, first.y - parent.y))
                clearance = _rectangle_clearance(first, parent)
                if clearance + 0.001 < config.support_body_clearance_mm:
                    support_body_violations.append(
                        {
                            "support_ref": first.ref,
                            "parent_ref": parent.ref,
                            "clearance_mm": round(clearance, 2),
                            "required_mm": config.support_body_clearance_mm,
                        }
                    )
        if not _inside_board(first, config):
            outside_board.append(first.ref)

    for p in state:
        placements[p.ref] = {
            "x": round(p.x, 2),
            "y": round(p.y, 2),
            "rotation": p.rotation,
            "layer": p.layer,
            "locked": p.locked,
            "constraint_locked": p.constraint_locked,
            "width_mm": p.width,
            "height_mm": p.height,
            "geometry_status": p.geometry_status,
        }
        if p.thermal_dissipation_w > 1.0:
            thermal_warnings.append(f"{p.ref}: {p.thermal_dissipation_w}W dissipation — ensure adequate copper area")

    plan = constraint_plan or _ConstraintPlan()
    constraint_evaluation = _constraint_evaluation(state, config, plan)
    return {
        "status": "ok",
        "placements": placements,
        "board_width_mm": config.board_width_mm,
        "board_height_mm": config.board_height_mm,
        "iterations": iterations,
        "final_cost": round(final_cost, 2),
        "initial_cost": round(initial_cost, 2),
        "strategy": config.strategy,
        "thermal_warnings": thermal_warnings,
        "constraint_evaluation": constraint_evaluation,
        "quality": {
            "overlaps": overlap_pairs,
            "outside_board": sorted(outside_board),
            "missing_parents": sorted(missing_parents),
            "support_body_violations": support_body_violations,
            "max_support_distance_mm": round(max(support_distances, default=0.0), 2),
            "legalization_moves": legalization_moves,
            "review_required": bool(
                overlap_pairs
                or outside_board
                or missing_parents
                or support_body_violations
                or constraint_evaluation["unsupported"]
                or constraint_evaluation["violations"]
            ),
        },
    }
