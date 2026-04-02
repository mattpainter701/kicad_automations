"""Managed silkscreen ownership helpers for KiCad boards."""

from __future__ import annotations

import json
from pathlib import Path

from .placement import is_locked

STATE_VERSION = 1
EXACT_TOLERANCE_MM = 0.2
PREVIOUS_TOLERANCE_MM = 1.5
EDGE_MARGIN_MM = 0.4
OBSTACLE_MARGIN_MM = 0.2
TEXT_WIDTH_FACTOR = 0.62
TEXT_HEIGHT_FACTOR = 1.2


def get_state_path(board_filename: str) -> Path:
    """Persist silk ownership next to the board file."""
    board_path = Path(board_filename)
    return board_path.with_name(f"{board_path.stem}.silkscreen_state.json")


def _layer_id(pcbnew, layer_name: str):
    return pcbnew.F_SilkS if layer_name == "F.SilkS" else pcbnew.B_SilkS


def _round_mm(value: float) -> float:
    return round(value, 3)


def _drawing_snapshot(drawing, pcbnew) -> dict:
    pos = drawing.GetPosition()
    size = drawing.GetTextSize()
    layer_id = drawing.GetLayer()
    layer_name = "F.SilkS" if layer_id == pcbnew.F_SilkS else "B.SilkS"
    return {
        "text": drawing.GetText(),
        "x": _round_mm(pcbnew.ToMM(pos.x)),
        "y": _round_mm(pcbnew.ToMM(pos.y)),
        "size": _round_mm(pcbnew.ToMM(size.x)),
        "layer": layer_name,
    }


def _spec_snapshot(spec: dict) -> dict:
    return {
        "text": spec["text"],
        "x": _round_mm(spec["x"]),
        "y": _round_mm(spec["y"]),
        "size": _round_mm(spec["size"]),
        "layer": spec["layer"],
    }


def _distance_sq(a_x: float, a_y: float, b_x: float, b_y: float) -> float:
    dx = a_x - b_x
    dy = a_y - b_y
    return dx * dx + dy * dy


def _box_from_center(
    text: str,
    x_mm: float,
    y_mm: float,
    size_mm: float,
    margin_mm: float = 0.0,
) -> dict:
    width_mm = max(size_mm, len(text) * size_mm * TEXT_WIDTH_FACTOR)
    height_mm = size_mm * TEXT_HEIGHT_FACTOR
    half_w = width_mm / 2.0 + margin_mm
    half_h = height_mm / 2.0 + margin_mm
    return {
        "x1": x_mm - half_w,
        "y1": y_mm - half_h,
        "x2": x_mm + half_w,
        "y2": y_mm + half_h,
    }


def _boxes_overlap(a: dict, b: dict) -> bool:
    return not (
        a["x2"] <= b["x1"]
        or a["x1"] >= b["x2"]
        or a["y2"] <= b["y1"]
        or a["y1"] >= b["y2"]
    )


def _box_outside_bounds(box: dict, bounds: dict) -> bool:
    return (
        box["x1"] < bounds["x1"] + EDGE_MARGIN_MM
        or box["y1"] < bounds["y1"] + EDGE_MARGIN_MM
        or box["x2"] > bounds["x2"] - EDGE_MARGIN_MM
        or box["y2"] > bounds["y2"] - EDGE_MARGIN_MM
    )


def _board_bounds(board, pcbnew) -> dict:
    if hasattr(board, "GetBoardEdgesBoundingBox"):
        bbox = board.GetBoardEdgesBoundingBox()
    else:
        bbox = board.GetBoundingBox()
    return {
        "x1": pcbnew.ToMM(bbox.GetX()),
        "y1": pcbnew.ToMM(bbox.GetY()),
        "x2": pcbnew.ToMM(bbox.GetX() + bbox.GetWidth()),
        "y2": pcbnew.ToMM(bbox.GetY() + bbox.GetHeight()),
    }


def _footprint_silk_layer(footprint, pcbnew) -> str:
    return "B.SilkS" if footprint.GetLayer() == pcbnew.B_Cu else "F.SilkS"


def _collect_footprint_boxes(board, pcbnew) -> dict[str, list[dict]]:
    obstacles = {"F.SilkS": [], "B.SilkS": []}
    for footprint in board.GetFootprints():
        bbox = footprint.GetBoundingBox()
        obstacles[_footprint_silk_layer(footprint, pcbnew)].append(
            {
                "x1": pcbnew.ToMM(bbox.GetX()) - OBSTACLE_MARGIN_MM,
                "y1": pcbnew.ToMM(bbox.GetY()) - OBSTACLE_MARGIN_MM,
                "x2": pcbnew.ToMM(bbox.GetX() + bbox.GetWidth()) + OBSTACLE_MARGIN_MM,
                "y2": pcbnew.ToMM(bbox.GetY() + bbox.GetHeight()) + OBSTACLE_MARGIN_MM,
            }
        )
    return obstacles


def _label_box(label: dict, margin_mm: float = OBSTACLE_MARGIN_MM) -> dict:
    return _box_from_center(label["text"], label["x"], label["y"], label["size"], margin_mm)


def _entry_box(entry: dict) -> dict:
    return _box_from_center(
        entry["text"],
        entry["x"],
        entry["y"],
        entry.get("size", 1.0),
        OBSTACLE_MARGIN_MM,
    )


def _candidate_offsets(spec: dict, bounds: dict) -> list[tuple[float, float]]:
    step = max(0.8, spec["size"] * 1.4)
    center_x = (bounds["x1"] + bounds["x2"]) / 2.0
    center_y = (bounds["y1"] + bounds["y2"]) / 2.0
    x_step = step if spec["x"] <= center_x else -step
    y_step = step if spec["y"] <= center_y else -step
    ring2 = step * 2.0
    return [
        (0.0, 0.0),
        (0.0, y_step),
        (x_step, 0.0),
        (-x_step, 0.0),
        (0.0, -y_step),
        (x_step, y_step),
        (-x_step, y_step),
        (x_step, -y_step),
        (-x_step, -y_step),
        (0.0, ring2 if y_step > 0 else -ring2),
        (ring2 if x_step > 0 else -ring2, 0.0),
        (0.0, -ring2 if y_step > 0 else ring2),
        (-ring2 if x_step > 0 else ring2, 0.0),
    ]


def _resolve_label_position(
    spec: dict,
    bounds: dict,
    footprint_boxes: dict[str, list[dict]],
    occupied_boxes: list[dict],
) -> dict:
    best = None
    for dx, dy in _candidate_offsets(spec, bounds):
        candidate = {**spec, "x": spec["x"] + dx, "y": spec["y"] + dy}
        label_box = _label_box(candidate)
        collision_count = 0
        if _box_outside_bounds(label_box, bounds):
            collision_count += 10
        for obstacle in footprint_boxes.get(spec["layer"], ()):
            if _boxes_overlap(label_box, obstacle):
                collision_count += 1
        for obstacle in occupied_boxes:
            if _boxes_overlap(label_box, obstacle):
                collision_count += 1
        score = (
            collision_count,
            _distance_sq(candidate["x"], candidate["y"], spec["x"], spec["y"]),
        )
        if best is None or score < best[0]:
            best = (score, candidate)
            if collision_count == 0:
                break
    return best[1] if best else spec


def _collect_silk_drawings(board, pcbnew) -> list[dict]:
    drawings = []
    for drawing in board.GetDrawings():
        if not hasattr(drawing, "GetText") or not hasattr(drawing, "GetPosition"):
            continue
        layer_id = drawing.GetLayer()
        if layer_id not in (pcbnew.F_SilkS, pcbnew.B_SilkS):
            continue
        pos = drawing.GetPosition()
        size = drawing.GetTextSize() if hasattr(drawing, "GetTextSize") else None
        drawings.append(
            {
                "drawing": drawing,
                "text": drawing.GetText(),
                "x": pcbnew.ToMM(pos.x),
                "y": pcbnew.ToMM(pos.y),
                "size": pcbnew.ToMM(size.x) if size is not None else 1.0,
                "layer": "F.SilkS" if layer_id == pcbnew.F_SilkS else "B.SilkS",
                "layer_id": layer_id,
                "locked": is_locked(drawing),
            }
        )
    return drawings


def _find_existing_label(
    entries: list[dict],
    desired: dict,
    claimed: set[int],
    tolerance_mm: float | None,
):
    layer_id = desired["layer_id"]
    best = None
    for entry in entries:
        drawing = entry["drawing"]
        if id(drawing) in claimed:
            continue
        if entry["layer_id"] != layer_id:
            continue
        if entry["text"] != desired["text"]:
            continue
        distance_sq = _distance_sq(entry["x"], entry["y"], desired["x"], desired["y"])
        if tolerance_mm is not None and distance_sq > tolerance_mm * tolerance_mm:
            continue
        score = (distance_sq, entry["locked"])
        if best is None or score < best[0]:
            best = (score, entry)
    return best[1] if best else None


def _apply_label_style(drawing, spec, pcbnew):
    drawing.SetText(spec["text"])
    drawing.SetPosition(pcbnew.VECTOR2I(pcbnew.FromMM(spec["x"]), pcbnew.FromMM(spec["y"])))
    drawing.SetTextSize(
        pcbnew.VECTOR2I(pcbnew.FromMM(spec["size"]), pcbnew.FromMM(spec["size"]))
    )
    drawing.SetTextThickness(pcbnew.FromMM(spec["size"] * 0.15))
    drawing.SetHorizJustify(pcbnew.GR_TEXT_H_ALIGN_CENTER)
    drawing.SetVertJustify(pcbnew.GR_TEXT_V_ALIGN_CENTER)
    drawing.SetLayer(spec["layer_id"])


def load_state(state_path: Path) -> dict:
    if not state_path.exists():
        return {"version": STATE_VERSION, "labels": {}}
    try:
        data = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"version": STATE_VERSION, "labels": {}}
    if not isinstance(data, dict):
        return {"version": STATE_VERSION, "labels": {}}
    return {"version": data.get("version", STATE_VERSION), "labels": data.get("labels", {})}


def save_state(state_path: Path, labels: dict):
    payload = {"version": STATE_VERSION, "labels": labels}
    state_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def sync_managed_silkscreen(
    board,
    labels: dict,
    adopt_current: bool = False,
    force: bool = False,
) -> dict:
    """Update only previously managed silk labels and optionally adopt/force."""
    import pcbnew

    state_path = get_state_path(board.GetFileName())
    prior_state = load_state(state_path)
    prior_labels = prior_state.get("labels", {})
    existing = _collect_silk_drawings(board, pcbnew)
    bounds = _board_bounds(board, pcbnew)
    footprint_boxes = _collect_footprint_boxes(board, pcbnew)
    claimed = set()
    new_state = {}
    stats = {
        "updated": 0,
        "created": 0,
        "removed": 0,
        "adopted": 0,
        "locked": 0,
        "nudged": 0,
        "created_ids": [],
        "updated_ids": [],
        "removed_ids": [],
        "adopted_ids": [],
        "locked_ids": [],
        "nudged_ids": [],
    }

    desired_specs = {}
    for label_id, spec in labels.items():
        desired_specs[label_id] = {
            **spec,
            "id": label_id,
            "layer_id": _layer_id(pcbnew, spec["layer"]),
        }

    reserved_ids = set()
    probe_claimed = set()
    for label_id, spec in desired_specs.items():
        drawing_entry = None
        prior = prior_labels.get(label_id)
        if prior:
            prior_match = {
                "text": prior.get("text", spec["text"]),
                "x": float(prior.get("x", spec["x"])),
                "y": float(prior.get("y", spec["y"])),
                "layer_id": _layer_id(pcbnew, prior.get("layer", spec["layer"])),
            }
            drawing_entry = _find_existing_label(
                existing, prior_match, probe_claimed, PREVIOUS_TOLERANCE_MM
            )
        if drawing_entry is None and adopt_current:
            drawing_entry = _find_existing_label(existing, spec, probe_claimed, None)
        if drawing_entry is None:
            drawing_entry = _find_existing_label(existing, spec, probe_claimed, EXACT_TOLERANCE_MM)
        if drawing_entry is not None:
            drawing_id = id(drawing_entry["drawing"])
            reserved_ids.add(drawing_id)
            probe_claimed.add(drawing_id)

    static_silk_obstacles = {"F.SilkS": [], "B.SilkS": []}
    for entry in existing:
        drawing_id = id(entry["drawing"])
        if drawing_id in reserved_ids:
            continue
        static_silk_obstacles[entry["layer"]].append(_entry_box(entry))

    placed_label_boxes = {"F.SilkS": [], "B.SilkS": []}

    for label_id, spec in desired_specs.items():
        drawing_entry = None
        prior = prior_labels.get(label_id)
        if prior:
            prior_match = {
                "text": prior.get("text", spec["text"]),
                "x": float(prior.get("x", spec["x"])),
                "y": float(prior.get("y", spec["y"])),
                "layer_id": _layer_id(pcbnew, prior.get("layer", spec["layer"])),
            }
            drawing_entry = _find_existing_label(existing, prior_match, claimed, PREVIOUS_TOLERANCE_MM)

        if drawing_entry is None and adopt_current:
            drawing_entry = _find_existing_label(existing, spec, claimed, None)

        if drawing_entry is None:
            drawing_entry = _find_existing_label(existing, spec, claimed, EXACT_TOLERANCE_MM)

        if drawing_entry is None:
            resolved_spec = _resolve_label_position(
                spec,
                bounds,
                footprint_boxes,
                static_silk_obstacles[spec["layer"]] + placed_label_boxes[spec["layer"]],
            )
            drawing = pcbnew.PCB_TEXT(board)
            _apply_label_style(drawing, resolved_spec, pcbnew)
            board.Add(drawing)
            new_state[label_id] = _spec_snapshot(resolved_spec)
            if _spec_snapshot(resolved_spec) != _spec_snapshot(spec):
                stats["nudged"] += 1
                stats["nudged_ids"].append(label_id)
            placed_label_boxes[resolved_spec["layer"]].append(_label_box(resolved_spec))
            stats["created"] += 1
            stats["created_ids"].append(label_id)
            continue

        drawing = drawing_entry["drawing"]
        claimed.add(id(drawing))
        if drawing_entry["locked"] and not force:
            after = _drawing_snapshot(drawing, pcbnew)
            new_state[label_id] = after
            placed_label_boxes[after["layer"]].append(_entry_box(after))
            stats["locked"] += 1
            stats["locked_ids"].append(label_id)
            continue

        before = _drawing_snapshot(drawing, pcbnew)
        if adopt_current and drawing_entry is not None and not force:
            after = _drawing_snapshot(drawing, pcbnew)
        else:
            resolved_spec = _resolve_label_position(
                spec,
                bounds,
                footprint_boxes,
                static_silk_obstacles[spec["layer"]] + placed_label_boxes[spec["layer"]],
            )
            _apply_label_style(drawing, resolved_spec, pcbnew)
            after = _spec_snapshot(resolved_spec)
            if after != _spec_snapshot(spec):
                stats["nudged"] += 1
                stats["nudged_ids"].append(label_id)
        new_state[label_id] = after
        placed_label_boxes[after["layer"]].append(_entry_box(after))
        if before == after:
            stats["adopted"] += 1
            stats["adopted_ids"].append(label_id)
        else:
            stats["updated"] += 1
            stats["updated_ids"].append(label_id)

    for label_id, prior in prior_labels.items():
        if label_id in desired_specs:
            continue
        prior_match = {
            "text": prior.get("text", ""),
            "x": float(prior.get("x", 0.0)),
            "y": float(prior.get("y", 0.0)),
            "layer_id": _layer_id(pcbnew, prior.get("layer", "F.SilkS")),
        }
        drawing_entry = _find_existing_label(existing, prior_match, claimed, PREVIOUS_TOLERANCE_MM)
        if drawing_entry is None:
            continue
        drawing = drawing_entry["drawing"]
        claimed.add(id(drawing))
        if drawing_entry["locked"] and not force:
            stats["locked"] += 1
            stats["locked_ids"].append(label_id)
            continue
        board.Remove(drawing)
        stats["removed"] += 1
        stats["removed_ids"].append(label_id)

    save_state(state_path, new_state)
    return stats
