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
from dataclasses import dataclass
from itertools import combinations
from pathlib import Path

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
    "SOT-23": (2.9, 1.3),
    "SOT-223": (6.5, 3.5),
    "SOIC-8": (5.0, 4.0),
    "SOIC-16": (10.3, 4.0),
    "TSSOP-16": (5.0, 4.4),
    "QFN-16": (3.0, 3.0),
    "QFN-24": (4.0, 4.0),
    "QFN-32": (5.0, 5.0),
    "QFN-48": (7.0, 7.0),
    "LQFP-48": (9.0, 9.0),
    "LQFP-64": (12.0, 12.0),
    "LQFP-100": (16.0, 16.0),
    "BGA": (15.0, 15.0),
    "USB-C": (9.0, 7.5),
}

# Category placement priority zones (x_pct, y_pct of board)
_ZONE_CENTERS: dict[str, tuple[float, float]] = {
    "power": (0.15, 0.15),
    "digital": (0.5, 0.4),
    "analog": (0.5, 0.7),
    "comms": (0.85, 0.4),
    "connector": (0.5, 0.95),
    "sensor": (0.85, 0.7),
    "passive": (0.5, 0.5),
}

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


def _estimate_size(comp: ComponentDef) -> tuple[float, float]:
    """Estimate component physical size from footprint string."""
    fp = (comp.footprint or "").upper()
    for pattern, size in _FOOTPRINT_SIZES.items():
        if pattern.upper() in fp:
            return size
    # Default based on category
    prefix = comp.source_ref[:1].upper() if comp.source_ref else ""
    if prefix in ("R", "C", "L"):
        return (1.6, 0.8)  # 0603 default
    if prefix == "U":
        return (5.0, 5.0)  # generic IC
    if prefix == "J":
        return (8.0, 5.0)  # connector
    return (2.0, 2.0)


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


def _init_placements(
    components: list[ComponentDef],
    config: PlacementConfig,
    thermal_specs: dict[str, dict],
    si_specs: dict[str, dict],
) -> list[ComponentPlacement]:
    """Create initial placement state with zone-based positions."""
    placements = []
    zone_counters: dict[str, int] = {}

    for comp in components:
        if not comp.source_ref:
            continue

        w, h = _estimate_size(comp)
        cat = (comp.category or "other").lower()
        if cat not in _ZONE_CENTERS:
            cat = "passive" if comp.source_ref[0] in "RCL" else "digital"

        zone_cx = _ZONE_CENTERS.get(cat, (0.5, 0.5))[0] * config.board_width_mm
        zone_cy = _ZONE_CENTERS.get(cat, (0.5, 0.5))[1] * config.board_height_mm

        idx = zone_counters.get(cat, 0)
        zone_counters[cat] = idx + 1
        cols = max(1, int(math.sqrt(idx + 1)))
        row, col = divmod(idx, cols)
        offset_x = col * (w + config.min_component_gap_mm + 1.0)
        offset_y = row * (h + config.min_component_gap_mm + 1.0)

        x = max(
            config.edge_clearance_mm + w / 2,
            min(zone_cx + offset_x, config.board_width_mm - config.edge_clearance_mm - w / 2),
        )
        y = max(
            config.edge_clearance_mm + h / 2,
            min(zone_cy + offset_y, config.board_height_mm - config.edge_clearance_mm - h / 2),
        )

        mpn = comp.mpn or ""
        thermal = thermal_specs.get(mpn, {})
        si = si_specs.get(mpn, {})

        placements.append(
            ComponentPlacement(
                ref=comp.source_ref,
                x=x,
                y=y,
                width=w,
                height=h,
                category=cat,
                is_power=cat == "power",
                thermal_dissipation_w=thermal.get("pdiss_max_w", 0.0)
                if isinstance(thermal.get("pdiss_max_w"), (int, float))
                else 0.0,
                requires_impedance_control=si.get("requires_impedance_control", False),
            )
        )

    return placements


def _overlap_area(a: ComponentPlacement, b: ComponentPlacement, gap: float = 0.0) -> float:
    """Calculate overlap area between two components (including gap)."""
    ax1, ay1 = a.x - a.width / 2 - gap, a.y - a.height / 2 - gap
    ax2, ay2 = a.x + a.width / 2 + gap, a.y + a.height / 2 + gap
    bx1, by1 = b.x - b.width / 2 - gap, b.y - b.height / 2 - gap
    bx2, by2 = b.x + b.width / 2 + gap, b.y + b.height / 2 + gap

    dx = min(ax2, bx2) - max(ax1, bx1)
    dy = min(ay2, by2) - max(ay1, by1)
    if dx > 0 and dy > 0:
        return dx * dy
    return 0.0


def _cost_overlap(placements: list[ComponentPlacement], gap: float) -> float:
    """Penalty for overlapping components."""
    total = 0.0
    for i in range(len(placements)):
        for j in range(i + 1, len(placements)):
            total += _overlap_area(placements[i], placements[j], gap)
    return total * 1000.0  # Heavy penalty


def _cost_boundary(placements: list[ComponentPlacement], config: PlacementConfig) -> float:
    """Penalty for components outside board boundary."""
    total = 0.0
    for p in placements:
        margin = config.edge_clearance_mm
        if p.x - p.width / 2 < margin:
            total += (margin - (p.x - p.width / 2)) ** 2
        if p.x + p.width / 2 > config.board_width_mm - margin:
            total += ((p.x + p.width / 2) - (config.board_width_mm - margin)) ** 2
        if p.y - p.height / 2 < margin:
            total += (margin - (p.y - p.height / 2)) ** 2
        if p.y + p.height / 2 > config.board_height_mm - margin:
            total += ((p.y + p.height / 2) - (config.board_height_mm - margin)) ** 2
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
        zone = _ZONE_CENTERS.get(p.category, (0.5, 0.5))
        ideal_x = zone[0] * config.board_width_mm
        ideal_y = zone[1] * config.board_height_mm
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
    """Collapse shared nets into weighted component-pair attractions."""
    pair_weights: dict[tuple[str, str], float] = {}
    for net_name, refs in _build_net_component_map(components).items():
        if len(refs) < 2:
            continue
        weight = _net_weight(net_name)
        if weight <= 0:
            continue
        for a, b in combinations(refs, 2):
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
    return total * 0.02


def _total_cost(
    placements: list[ComponentPlacement],
    config: PlacementConfig,
    connectivity_pairs: dict[tuple[str, str], float] | None = None,
) -> float:
    """Compute total placement cost based on strategy."""
    cost = _cost_overlap(placements, config.min_component_gap_mm)
    cost += _cost_boundary(placements, config)

    if config.strategy in ("thermal", "balanced"):
        cost += _cost_thermal(placements)
    if config.strategy in ("si", "balanced"):
        cost += _cost_connectivity(placements, connectivity_pairs or {})
    if config.strategy in ("cost", "balanced"):
        cost += _cost_zone(placements, config)

    return cost


def _perturb(
    placements: list[ComponentPlacement], config: PlacementConfig, rng: random.Random
) -> list[ComponentPlacement]:
    """Create a neighbor solution by moving one component."""
    new = [ComponentPlacement(**p.__dict__) for p in placements]
    idx = rng.randint(0, len(new) - 1)
    p = new[idx]

    move_type = rng.random()
    if move_type < 0.6:
        # Small move
        p.x += rng.gauss(0, 2.0)
        p.y += rng.gauss(0, 2.0)
    elif move_type < 0.85:
        # Swap two components
        other = rng.randint(0, len(new) - 1)
        if other != idx:
            new[idx].x, new[other].x = new[other].x, new[idx].x
            new[idx].y, new[other].y = new[other].y, new[idx].y
    else:
        # Rotate
        p.rotation = rng.choice([0, 90, 180, 270])

    # Clamp to board
    margin = config.edge_clearance_mm
    p.x = max(margin + p.width / 2, min(p.x, config.board_width_mm - margin - p.width / 2))
    p.y = max(margin + p.height / 2, min(p.y, config.board_height_mm - margin - p.height / 2))

    return new


def optimize_placement(
    components: list[ComponentDef],
    *,
    config: PlacementConfig | None = None,
    specs_dir: str | Path | None = None,
) -> dict:
    """Run simulated annealing placement optimizer.

    Args:
        components: List of ComponentDef from compiled design.
        config: Optimizer configuration (defaults to balanced strategy).
        specs_dir: Path to specs/ directory with thermal/SI JSON files.

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

    specs_path = Path(specs_dir) if specs_dir else None
    thermal_specs = _load_thermal_specs(specs_path)
    si_specs = _load_si_specs(specs_path)
    connectivity_pairs = _build_connectivity_pairs(components)

    state = _init_placements(components, config, thermal_specs, si_specs)

    if not state:
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
        }

    if config.strategy == "simple":
        # Skip optimization, return initial zone-based placement
        return _build_result(state, config, 0, 0.0, 0.0)

    rng = random.Random(config.seed)
    current_cost = _total_cost(state, config, connectivity_pairs)
    initial_cost = current_cost
    best_state = state
    best_cost = current_cost
    temp = config.initial_temp

    for i in range(config.iterations):
        candidate = _perturb(state, config, rng)
        candidate_cost = _total_cost(candidate, config, connectivity_pairs)
        delta = candidate_cost - current_cost

        if delta < 0 or rng.random() < math.exp(-delta / max(temp, 0.001)):
            state = candidate
            current_cost = candidate_cost
            if current_cost < best_cost:
                best_state = state
                best_cost = current_cost

        temp *= config.cooling_rate

    return _build_result(best_state, config, config.iterations, initial_cost, best_cost)


def _build_result(
    state: list[ComponentPlacement],
    config: PlacementConfig,
    iterations: int,
    initial_cost: float,
    final_cost: float,
) -> dict:
    """Build the result dict from optimizer state."""
    placements = {}
    thermal_warnings = []

    for p in state:
        placements[p.ref] = {
            "x": round(p.x, 2),
            "y": round(p.y, 2),
            "rotation": p.rotation,
            "layer": p.layer,
        }
        if p.thermal_dissipation_w > 1.0:
            thermal_warnings.append(f"{p.ref}: {p.thermal_dissipation_w}W dissipation — ensure adequate copper area")

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
    }
