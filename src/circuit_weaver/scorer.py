"""Schematic aesthetics scorer — rule-based quality gate.

Scores a SheetLayout on readability metrics and returns a numeric
score (0-100) with per-metric breakdown.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from .placer import SheetLayout, component_body_bounds
from .primitives import PAPER_SIZES, TITLE_BLOCK_H


@dataclass
class MetricScore:
    name: str
    raw_value: float
    score: float
    weight: float = 1.0
    detail: str = ""


@dataclass
class LayoutScore:
    sheet_name: str
    total: float
    grade: str
    metrics: list[MetricScore] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "sheet": self.sheet_name,
            "total": round(self.total, 1),
            "grade": self.grade,
            "metrics": [
                {
                    "name": m.name,
                    "raw": round(m.raw_value, 3),
                    "score": round(m.score, 1),
                    "detail": m.detail,
                }
                for m in self.metrics
            ],
        }


def _grade(score: float) -> str:
    if score >= 90:
        return "A"
    if score >= 80:
        return "B"
    if score >= 70:
        return "C"
    if score >= 60:
        return "D"
    return "F"


def _spacing_uniformity(layout: SheetLayout) -> MetricScore:
    positions = [(pc.x, pc.y) for pc in layout.placed_ics]
    if len(positions) < 2:
        return MetricScore("spacing_uniformity", 0.0, 100.0, 1.5, "< 2 ICs")

    nn_dists = []
    for i, (x1, y1) in enumerate(positions):
        min_d = float("inf")
        for j, (x2, y2) in enumerate(positions):
            if i != j:
                min_d = min(min_d, math.hypot(x2 - x1, y2 - y1))
        nn_dists.append(min_d)

    mean_d = sum(nn_dists) / len(nn_dists)
    if mean_d <= 0:
        return MetricScore("spacing_uniformity", 0.0, 50.0, 1.5, "zero mean")
    std_d = math.sqrt(sum((d - mean_d) ** 2 for d in nn_dists) / len(nn_dists))
    cv = std_d / mean_d
    score = max(0, min(100, 100 - cv * 80))
    return MetricScore(
        "spacing_uniformity",
        cv,
        score,
        1.5,
        f"CV={cv:.2f}, mean_nn={mean_d:.1f}mm",
    )


def _whitespace_ratio(layout: SheetLayout) -> MetricScore:
    pw, ph = PAPER_SIZES.get(layout.paper, PAPER_SIZES["A3"])
    usable_h = ph - TITLE_BLOCK_H
    page_area = pw * usable_h
    if page_area <= 0:
        return MetricScore("whitespace_ratio", 0.0, 50.0, 1.0, "zero page")

    min_x = min_y = float("inf")
    max_x = max_y = float("-inf")
    for pc in layout.placed_ics:
        left, top, right, bottom = component_body_bounds(pc)
        min_x, min_y = min(min_x, left), min(min_y, top)
        max_x, max_y = max(max_x, right), max(max_y, bottom)
    for pp in layout.placed_passives:
        min_x, min_y = min(min_x, pp.x - 5), min(min_y, pp.y - 3)
        max_x, max_y = max(max_x, pp.x + 5), max(max_y, pp.y + 3)

    if min_x == float("inf"):
        return MetricScore("whitespace_ratio", 0.0, 80.0, 1.0, "no content")

    content_area = max(0, max_x - min_x) * max(0, max_y - min_y)
    ratio = content_area / page_area

    if 0.15 <= ratio <= 0.40:
        score = 100.0
    elif ratio < 0.15:
        score = max(0, ratio / 0.15 * 100)
    else:
        score = max(0, 100 - (ratio - 0.40) * 200)

    return MetricScore(
        "whitespace_ratio",
        ratio,
        score,
        1.0,
        f"ratio={ratio:.1%}",
    )


def _label_overlap_potential(layout: SheetLayout) -> MetricScore:
    anchors = [(a.x, a.y) for a in layout.local_net_anchors if a.render_mode != "junction"]
    if len(anchors) < 2:
        return MetricScore("label_overlap", 0, 100.0, 1.5, "< 2 labels")

    close_pairs = 0
    for i in range(len(anchors)):
        for j in range(i + 1, len(anchors)):
            if math.hypot(anchors[j][0] - anchors[i][0], anchors[j][1] - anchors[i][1]) < 5.0:
                close_pairs += 1

    max_pairs = len(anchors) * (len(anchors) - 1) // 2
    overlap_ratio = close_pairs / max(1, max_pairs)
    score = max(0, 100 - overlap_ratio * 500)
    return MetricScore(
        "label_overlap",
        close_pairs,
        score,
        1.5,
        f"{close_pairs} close pairs / {max_pairs}",
    )


def _wire_crossing_estimate(layout: SheetLayout) -> MetricScore:
    wires = layout.local_wires
    if len(wires) < 2:
        return MetricScore("wire_crossings", 0, 100.0, 2.0, "< 2 wires")

    crossings = 0
    for i in range(len(wires)):
        x1a, y1a, x1b, y1b = wires[i]
        for j in range(i + 1, len(wires)):
            x2a, y2a, x2b, y2b = wires[j]
            if max(x1a, x1b) < min(x2a, x2b) or max(x2a, x2b) < min(x1a, x1b):
                continue
            if max(y1a, y1b) < min(y2a, y2b) or max(y2a, y2b) < min(y1a, y1b):
                continue
            h1 = abs(y1b - y1a) < 0.1
            v1 = abs(x1b - x1a) < 0.1
            h2 = abs(y2b - y2a) < 0.1
            v2 = abs(x2b - x2a) < 0.1
            if (h1 and h2) or (v1 and v2):
                continue
            crossings += 1

    score = max(0, 100 - crossings * 15)
    return MetricScore(
        "wire_crossings",
        crossings,
        score,
        2.0,
        f"{crossings} crossings from {len(wires)} wires",
    )


def _aspect_ratio(layout: SheetLayout) -> MetricScore:
    pw, ph = PAPER_SIZES.get(layout.paper, PAPER_SIZES["A3"])
    usable_h = ph - TITLE_BLOCK_H
    page_aspect = pw / usable_h if usable_h > 0 else 1.0

    min_x = min_y = float("inf")
    max_x = max_y = float("-inf")
    for pc in layout.placed_ics:
        left, top, right, bottom = component_body_bounds(pc)
        min_x, min_y = min(min_x, left), min(min_y, top)
        max_x, max_y = max(max_x, right), max(max_y, bottom)

    if min_x == float("inf"):
        return MetricScore("aspect_ratio", 1.0, 80.0, 0.5, "no content")

    cw = max(1.0, max_x - min_x)
    ch = max(1.0, max_y - min_y)
    content_aspect = cw / ch
    ratio = content_aspect / page_aspect if page_aspect > 0 else 1.0
    deviation = abs(math.log(max(0.1, ratio)))
    score = max(0, 100 - deviation * 50)
    return MetricScore(
        "aspect_ratio",
        ratio,
        score,
        0.5,
        f"content={content_aspect:.2f}, page={page_aspect:.2f}",
    )


def _component_count_density(layout: SheetLayout) -> MetricScore:
    n_ics = len(layout.placed_ics)
    n_passives = len(layout.placed_passives)
    paper_rank = {"A4": 0, "A3": 1, "A2": 2, "A1": 3, "A0": 4}.get(layout.paper, 1)
    targets = [(2, 5), (3, 15), (8, 30), (15, 60), (30, 100)]
    low, high = targets[min(paper_rank, len(targets) - 1)]

    if low <= n_ics <= high:
        score = 100.0
    elif n_ics < low:
        score = max(40, n_ics / max(1, low) * 100)
    else:
        score = max(40, 100 - (n_ics - high) / max(1, high) * 100)

    return MetricScore(
        "density",
        n_ics,
        score,
        0.5,
        f"{n_ics} ICs + {n_passives} passives on {layout.paper}",
    )


def score_layout(layout: SheetLayout) -> LayoutScore:
    """Score a single sheet layout on readability metrics (0-100, A-F)."""
    metrics = [
        _spacing_uniformity(layout),
        _whitespace_ratio(layout),
        _label_overlap_potential(layout),
        _wire_crossing_estimate(layout),
        _aspect_ratio(layout),
        _component_count_density(layout),
    ]
    total_weight = sum(m.weight for m in metrics)
    if total_weight <= 0:
        return LayoutScore(layout.name, 50.0, "D", metrics)
    weighted_sum = sum(m.score * m.weight for m in metrics)
    total = weighted_sum / total_weight
    return LayoutScore(layout.name, total, _grade(total), metrics)


def score_project(layouts: list[SheetLayout]) -> dict:
    """Score all sheets and return aggregate results."""
    sheet_scores = [score_layout(layout) for layout in layouts]
    if not sheet_scores:
        return {"total": 0.0, "grade": "F", "sheets": []}
    avg = sum(s.total for s in sheet_scores) / len(sheet_scores)
    return {
        "total": round(avg, 1),
        "grade": _grade(avg),
        "sheets": [s.to_dict() for s in sheet_scores],
    }


# ================================================================
# Electrical quality scoring (Sprint 6)
# ================================================================


@dataclass
class ElectricalQualityScore:
    """Aggregate electrical quality score for a set of components."""

    total: float
    grade: str
    pin_coverage_pct: float
    decoupling_coverage_pct: float
    power_pin_coverage_pct: float
    validation_pass_pct: float
    details: dict

    def to_dict(self) -> dict:
        return {
            "total": round(self.total, 1),
            "grade": self.grade,
            "pin_coverage_pct": round(self.pin_coverage_pct, 1),
            "decoupling_coverage_pct": round(self.decoupling_coverage_pct, 1),
            "power_pin_coverage_pct": round(self.power_pin_coverage_pct, 1),
            "validation_pass_pct": round(self.validation_pass_pct, 1),
            "details": self.details,
        }


def score_electrical_quality(components, validation_results=None) -> ElectricalQualityScore:
    """Score the electrical quality of a component set (0-100, A-F).

    Metrics:
    - Pin coverage: % of IC pins explicitly connected (vs blanket NC)
    - Decoupling coverage: % of power pins with bypass caps
    - Power pin coverage: % of power_in pins assigned to rails
    - Validation pass rate: % of validation checks passing
    """
    total_ic_pins = 0
    connected_ic_pins = 0
    total_power_pins = 0
    assigned_power_pins = 0
    total_decouple_targets = 0
    covered_decouple = 0

    for comp in components:
        if comp.ref_prefix.upper() not in ("U", "IC"):
            continue
        handled = set(comp.pin_nets) | set(comp.power_pins) | comp.explicit_no_connects
        for strap in comp.straps:
            handled.add(strap.pin)
        for pin in comp.pins:
            total_ic_pins += 1
            if pin.number in handled:
                connected_ic_pins += 1
            if pin.electrical_type == "power_in":
                total_power_pins += 1
                if pin.number in comp.power_pins:
                    assigned_power_pins += 1

        # Decoupling: count non-GND power pins
        for _pnum, net in comp.power_pins.items():
            if not any(net.upper().startswith(g) for g in ("GND", "AGND", "DGND")):
                total_decouple_targets += 1
                if any(bc.net == net or bc.pin == _pnum for bc in comp.bypass_caps):
                    covered_decouple += 1

    pin_pct = (connected_ic_pins / max(1, total_ic_pins)) * 100
    power_pct = (assigned_power_pins / max(1, total_power_pins)) * 100
    decouple_pct = (covered_decouple / max(1, total_decouple_targets)) * 100

    # Validation pass rate
    val_pass_pct = 100.0
    if validation_results:
        passing = sum(1 for r in validation_results if r.status == "PASS")
        val_pass_pct = (passing / max(1, len(validation_results))) * 100

    # Weighted total
    total = (pin_pct * 0.25 + power_pct * 0.30 + decouple_pct * 0.25 + val_pass_pct * 0.20)

    return ElectricalQualityScore(
        total=total,
        grade=_grade(total),
        pin_coverage_pct=pin_pct,
        decoupling_coverage_pct=decouple_pct,
        power_pin_coverage_pct=power_pct,
        validation_pass_pct=val_pass_pct,
        details={
            "total_ic_pins": total_ic_pins,
            "connected_ic_pins": connected_ic_pins,
            "total_power_pins": total_power_pins,
            "assigned_power_pins": assigned_power_pins,
            "decoupling_targets": total_decouple_targets,
            "decoupling_covered": covered_decouple,
        },
    )
