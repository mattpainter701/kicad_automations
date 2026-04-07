"""Panelization hints generator.

Suggests panel layouts for small boards, calculates breakaway positions,
and estimates cost savings from panelization.
"""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass
class PanelConfig:
    max_panel_width_mm: float = 100.0
    max_panel_height_mm: float = 100.0
    rail_width_mm: float = 5.0
    board_spacing_mm: float = 2.0
    edge_rail_mm: float = 5.0
    breakaway_type: str = "v-cut"
    mouse_bite_hole_mm: float = 0.5
    mouse_bite_pitch_mm: float = 0.8


def suggest_panel(
    board_width_mm: float,
    board_height_mm: float,
    *,
    qty: int = 100,
    config: PanelConfig | None = None,
    edge_clearance_mm: float = 0.3,
) -> dict:
    """Suggest optimal panel layout. Returns dict with panel_options, cost_estimate, design_rules."""
    if config is None:
        config = PanelConfig()

    warnings: list[str] = []
    design_rules: list[str] = []

    if min(board_width_mm, board_height_mm) < 6:
        warnings.append(
            f"Board minimum dimension {min(board_width_mm, board_height_mm)}mm is below typical fab minimum (6mm)"
        )
    if board_width_mm > config.max_panel_width_mm - 2 * config.edge_rail_mm:
        warnings.append("Board width exceeds panelizable area")
    if board_height_mm > config.max_panel_height_mm - 2 * config.edge_rail_mm:
        warnings.append("Board height exceeds panelizable area")

    design_rules.append(f"Keep copper >= {edge_clearance_mm}mm from board edge for {config.breakaway_type}")
    if config.breakaway_type == "v-cut":
        design_rules.append("V-cut: no copper on breakaway line; boards must have straight edges")
        design_rules.append("V-cut boards must be rectangular (no internal cutouts crossing the cut)")
    else:
        design_rules.append(f"Mouse-bite: {config.mouse_bite_hole_mm}mm holes at {config.mouse_bite_pitch_mm}mm pitch")
        design_rules.append("Mouse-bite allows non-rectangular boards and internal cutouts")
    design_rules.append("Preserve at least one fiducial per board for pick-and-place alignment")

    options: list[dict] = []
    for orientation, bw, bh in [
        ("normal", board_width_mm, board_height_mm),
        ("rotated", board_height_mm, board_width_mm),
    ]:
        usable_w = config.max_panel_width_mm - 2 * config.edge_rail_mm
        usable_h = config.max_panel_height_mm - 2 * config.edge_rail_mm
        cols = max(1, int(usable_w / (bw + config.board_spacing_mm)))
        rows = max(1, int(usable_h / (bh + config.board_spacing_mm)))
        panel_w = cols * bw + (cols - 1) * config.board_spacing_mm + 2 * config.edge_rail_mm
        panel_h = rows * bh + (rows - 1) * config.board_spacing_mm + 2 * config.edge_rail_mm
        boards_per = cols * rows
        if boards_per < 1:
            continue

        panels_needed = math.ceil(qty / boards_per)
        utilization = (cols * rows * bw * bh) / (panel_w * panel_h) * 100

        breakaway_x = [
            round(config.edge_rail_mm + c * bw + (c - 0.5) * config.board_spacing_mm, 2) for c in range(1, cols)
        ]
        breakaway_y = [
            round(config.edge_rail_mm + r * bh + (r - 0.5) * config.board_spacing_mm, 2) for r in range(1, rows)
        ]

        options.append(
            {
                "cols": cols,
                "rows": rows,
                "boards_per_panel": boards_per,
                "panel_width_mm": round(panel_w, 1),
                "panel_height_mm": round(panel_h, 1),
                "panels_needed": panels_needed,
                "total_boards": panels_needed * boards_per,
                "waste_boards": panels_needed * boards_per - qty,
                "utilization_pct": round(utilization, 1),
                "orientation": orientation,
                "breakaway_type": config.breakaway_type,
                "breakaway_positions": {"x_lines_mm": breakaway_x, "y_lines_mm": breakaway_y},
            }
        )

    seen: set[int] = set()
    unique = []
    for opt in options:
        if opt["boards_per_panel"] not in seen:
            seen.add(opt["boards_per_panel"])
            unique.append(opt)
    options = sorted(unique, key=lambda o: o["boards_per_panel"], reverse=True)

    recommended = 0
    if len(options) > 1:
        recommended = max(range(len(options)), key=lambda i: options[i]["utilization_pct"])

    cost_estimate: dict = {}
    if options:
        best = options[recommended]
        per_panel = 2.0 if best["panels_needed"] <= 5 else (1.0 if best["panels_needed"] <= 30 else 0.50)
        panel_cost = best["panels_needed"] * per_panel
        per_board_panel = panel_cost / qty if qty > 0 else 0
        single_cost = math.ceil(qty / 5) * 2.0
        per_board_single = single_cost / qty if qty > 0 else 0
        cost_estimate = {
            "panelized": {
                "panels": best["panels_needed"],
                "estimated_cost": round(panel_cost, 2),
                "per_board": round(per_board_panel, 4),
            },
            "single_boards": {
                "orders": math.ceil(qty / 5),
                "estimated_cost": round(single_cost, 2),
                "per_board": round(per_board_single, 4),
            },
            "savings_pct": round((1 - per_board_panel / max(per_board_single, 0.001)) * 100, 1)
            if per_board_single > 0
            else 0,
            "note": "Rough estimate based on JLCPCB standard pricing. Actual costs vary by specs.",
        }

    return {
        "status": "ok",
        "board_size": {"width": board_width_mm, "height": board_height_mm},
        "qty_requested": qty,
        "panel_options": options,
        "recommended": recommended,
        "cost_estimate": cost_estimate,
        "warnings": warnings,
        "design_rules": design_rules,
    }
