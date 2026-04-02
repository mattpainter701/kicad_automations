"""Generic footprint matching helpers for placement automation."""

from __future__ import annotations

import re


def _normalize_value_text(raw: str) -> str:
    """Return a normalized passive value string for loose matching."""
    text = (raw or "").strip().lower()
    text = text.replace(" ", "").replace("µ", "u").replace("μ", "u")
    text = text.replace("farads", "f").replace("farad", "f")

    text = re.sub(r"(\d)([pnumk])(\d)", r"\1.\3\2", text)

    for suffix in ("ohms", "ohm", "ω"):
        if text.endswith(suffix):
            text = text[: -len(suffix)]
    if text.endswith("f") and len(text) > 1:
        text = text[:-1]

    return text


def _parse_numeric_value(raw: str) -> float | None:
    """Parse common passive formats like 100nF, 0.1uF, 4u7."""
    text = _normalize_value_text(raw)
    match = re.fullmatch(r"(\d+(?:\.\d+)?)([pnumk]?)", text)
    if not match:
        return None

    magnitude = float(match.group(1))
    scale = {
        "": 1.0,
        "p": 1e-12,
        "n": 1e-9,
        "u": 1e-6,
        "m": 1e-3,
        "k": 1e3,
    }[match.group(2)]
    return magnitude * scale


def values_match(expected: str, actual: str) -> bool:
    """Compare passive values across equivalent spellings."""
    expected_value = _parse_numeric_value(expected)
    actual_value = _parse_numeric_value(actual)
    if expected_value is not None and actual_value is not None:
        return abs(expected_value - actual_value) <= max(expected_value, actual_value) * 0.01

    normalized_expected = _normalize_value_text(expected)
    normalized_actual = _normalize_value_text(actual)
    return (
        normalized_expected == normalized_actual
        or normalized_expected in normalized_actual
        or normalized_actual in normalized_expected
    )


def footprint_matches_keyword(footprint, keyword: str) -> bool:
    """Check the footprint name for a package keyword like 0402 or 0805."""
    if hasattr(footprint, "GetFPID"):
        try:
            name = footprint.GetFPID().GetUniStringLibItemName()
        except AttributeError:
            name = footprint.GetFPID().GetLibItemName()
    else:
        name = getattr(getattr(footprint, "definition", None), "id", None)
        name = getattr(name, "name", "")
    return keyword.lower() in (name or "").lower()


def footprint_has_net(footprint, net_name: str) -> bool:
    """Return True if any pad on the footprint is connected to the target net."""
    if hasattr(footprint, "Pads"):
        for pad in footprint.Pads():
            if pad.GetNetname() == net_name:
                return True
    else:
        for pad in getattr(getattr(footprint, "definition", None), "pads", []):
            if getattr(getattr(pad, "net", None), "name", None) == net_name:
                return True
    return False


def footprint_value(footprint) -> str:
    """Return the value text for pcbnew or kipy footprint objects."""
    if hasattr(footprint, "GetValue"):
        return footprint.GetValue()
    value_field = getattr(footprint, "value_field", None)
    if value_field is not None:
        return getattr(getattr(value_field, "text", None), "value", "")
    return ""


def footprint_ref(footprint) -> str:
    """Return the reference designator for pcbnew or kipy footprint objects."""
    if hasattr(footprint, "GetReference"):
        return footprint.GetReference()
    ref_field = getattr(footprint, "reference_field", None)
    if ref_field is not None:
        return getattr(getattr(ref_field, "text", None), "value", "")
    return ""


def footprint_position_mm(footprint) -> tuple[float, float]:
    """Return footprint position in mm for pcbnew or kipy footprint objects."""
    if hasattr(footprint, "GetPosition"):
        import pcbnew

        pos = footprint.GetPosition()
        return pcbnew.ToMM(pos.x), pcbnew.ToMM(pos.y)
    pos = getattr(footprint, "position", None)
    if pos is not None:
        return pos.x / 1e6, pos.y / 1e6
    return 0.0, 0.0


def iter_board_footprints(board):
    """Yield footprints from pcbnew or kipy board objects."""
    if hasattr(board, "GetFootprints"):
        return board.GetFootprints()
    return board.get_footprints()


def is_locked(footprint) -> bool:
    """Handle KiCad API variation for locked footprints."""
    if hasattr(footprint, "IsLocked"):
        return bool(footprint.IsLocked())
    if hasattr(footprint, "GetLocked"):
        return bool(footprint.GetLocked())
    return False


def find_matching_capacitor(
    board,
    used_refs: set[str],
    rail: str,
    value: str,
    fp_keyword: str,
    target_x_mm: float,
    target_y_mm: float,
    allowed_refs: tuple[str, ...] | None = None,
):
    """Return the best matching capacitor for a decoupling slot."""
    candidates = []
    allowed_ref_set = set(allowed_refs or ())
    for footprint in iter_board_footprints(board):
        ref = footprint_ref(footprint)
        if ref in used_refs or not ref.startswith("C") or is_locked(footprint):
            continue
        if allowed_ref_set and ref not in allowed_ref_set:
            continue
        if not footprint_matches_keyword(footprint, fp_keyword):
            continue
        if not values_match(value, footprint_value(footprint)):
            continue
        if not footprint_has_net(footprint, rail):
            continue

        x_mm, y_mm = footprint_position_mm(footprint)
        dx = target_x_mm - x_mm
        dy = target_y_mm - y_mm
        distance_sq = dx * dx + dy * dy
        candidates.append((distance_sq, ref, footprint))

    if not candidates:
        return None

    candidates.sort(key=lambda item: (item[0], item[1]))
    return candidates[0][2]
