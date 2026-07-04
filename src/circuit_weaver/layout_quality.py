"""Geometric layout-quality analysis of emitted KiCad schematics.

Parses a generated ``.kicad_sch`` the way KiCad would — tokenizing the
S-expressions and rebuilding symbol bounding boxes from the embedded
``lib_symbols`` geometry — and reports the two invariants that make
generated schematics read as sloppy when violated:

- **symbol-body overlaps** — two placed symbol bodies sharing area
  (stacked support passives are the canonical failure);
- **wire-body crossings** — wire segments running through a symbol body
  interior.

The analyzer is deliberately independent of the placer/generator geometry
passes: it reads what was actually emitted, so a regression in any
placement or routing pass surfaces here regardless of which pass caused
it. The test suite gates on it (``tests/test_layout_quality.py``) and the
generator runs it after emitting each sheet to surface quality warnings
on real designs.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path

__all__ = [
    "LayoutQualityReport",
    "analyze_schematic_file",
    "analyze_schematic_text",
]


@dataclass
class LayoutQualityReport:
    """Result of analyzing one emitted schematic sheet."""

    symbols: int = 0
    overlaps: list[tuple[str, str, float]] = field(default_factory=list)
    wire_body_crossings: int = 0

    @property
    def clean(self) -> bool:
        return not self.overlaps and self.wire_body_crossings == 0

    def summary(self) -> str:
        if self.clean:
            return f"{self.symbols} symbols, no overlaps, no wire-body crossings"
        parts = [f"{self.symbols} symbols"]
        if self.overlaps:
            pairs = ", ".join(f"{a}/{b}" for a, b, _area in self.overlaps[:4])
            parts.append(f"{len(self.overlaps)} overlapping symbol pair(s) ({pairs})")
        if self.wire_body_crossings:
            parts.append(f"{self.wire_body_crossings} wire segment(s) crossing symbol bodies")
        return ", ".join(parts)


def _tokenize(text: str) -> list[str]:
    out: list[str] = []
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if c in "()":
            out.append(c)
            i += 1
        elif c.isspace():
            i += 1
        elif c == '"':
            j = i + 1
            buf = []
            while j < n:
                if text[j] == "\\" and j + 1 < n:
                    buf.append(text[j + 1])
                    j += 2
                    continue
                if text[j] == '"':
                    break
                buf.append(text[j])
                j += 1
            out.append('"' + "".join(buf))
            i = j + 1
        else:
            j = i
            while j < n and not text[j].isspace() and text[j] not in "()":
                j += 1
            out.append(text[i:j])
            i = j
    return out


def _parse(tokens: list[str]):
    def walk(idx: int):
        assert tokens[idx] == "("
        idx += 1
        node: list = []
        while tokens[idx] != ")":
            if tokens[idx] == "(":
                child, idx = walk(idx)
                node.append(child)
            else:
                node.append(tokens[idx])
                idx += 1
        return node, idx + 1

    node, _ = walk(0)
    return node


def _find_all(node, name):
    for item in node:
        if isinstance(item, list) and item and item[0] == name:
            yield item


def _find_one(node, name):
    for item in _find_all(node, name):
        return item
    return None


def _sval(x):
    return x[1:] if isinstance(x, str) and x.startswith('"') else x


def _lib_symbol_bboxes(root) -> dict[str, tuple[float, float, float, float]]:
    """Bounding box of each lib symbol's drawn rectangles (the body)."""
    boxes: dict[str, tuple[float, float, float, float]] = {}
    libs = _find_one(root, "lib_symbols")
    if not libs:
        return boxes
    for sym in _find_all(libs, "symbol"):
        name = _sval(sym[1])
        xs: list[float] = []
        ys: list[float] = []
        stack = [sym]
        while stack:
            cur = stack.pop()
            for item in cur:
                if not isinstance(item, list):
                    continue
                if item[0] == "rectangle":
                    st = _find_one(item, "start")
                    en = _find_one(item, "end")
                    if st and en:
                        xs += [float(st[1]), float(en[1])]
                        ys += [float(st[2]), float(en[2])]
                elif item[0] == "symbol":
                    stack.append(item)
        if xs:
            boxes[name] = (min(xs), min(ys), max(xs), max(ys))
    return boxes


def _instance_bboxes(root, lib_boxes) -> list[tuple[str, tuple[float, float, float, float]]]:
    """Placed-instance body boxes, rotation applied."""
    out = []
    for sym in _find_all(root, "symbol"):
        lid = _find_one(sym, "lib_id")
        at = _find_one(sym, "at")
        if not lid or not at:
            continue
        lib = _sval(lid[1])
        x, y = float(at[1]), float(at[2])
        rot = float(at[3]) if len(at) > 3 else 0.0
        ref = "?"
        for prop in _find_all(sym, "property"):
            if _sval(prop[1]) == "Reference":
                ref = _sval(prop[2])
        bb = lib_boxes.get(lib)
        if not bb:
            continue
        rad = math.radians(rot)
        corners = []
        for cx, cy in ((bb[0], bb[1]), (bb[0], bb[3]), (bb[2], bb[1]), (bb[2], bb[3])):
            rx = cx * math.cos(rad) - cy * math.sin(rad)
            ry = cx * math.sin(rad) + cy * math.cos(rad)
            corners.append((x + rx, y - ry))
        xs = [c[0] for c in corners]
        ys = [c[1] for c in corners]
        out.append((ref, (min(xs), min(ys), max(xs), max(ys))))
    return out


def _wire_segments(root) -> list[tuple[tuple[float, float], tuple[float, float]]]:
    segs = []
    for w in _find_all(root, "wire"):
        pts = _find_one(w, "pts")
        if not pts:
            continue
        xy = [(float(p[1]), float(p[2])) for p in _find_all(pts, "xy")]
        segs.extend(zip(xy, xy[1:]))
    return segs


def _overlap_area(a, b) -> float:
    w = min(a[2], b[2]) - max(a[0], b[0])
    h = min(a[3], b[3]) - max(a[1], b[1])
    return w * h if (w > 0 and h > 0) else 0.0


def _seg_crosses_box(seg, box, shrink: float = 0.3) -> bool:
    """True when a wire segment passes through the (slightly shrunk) box."""
    (x1, y1), (x2, y2) = seg
    x0, y0, x3, y3 = box[0] + shrink, box[1] + shrink, box[2] - shrink, box[3] - shrink
    if x0 >= x3 or y0 >= y3:
        return False
    if max(x1, x2) <= x0 or min(x1, x2) >= x3 or max(y1, y2) <= y0 or min(y1, y2) >= y3:
        return False
    if x1 == x2:
        return x0 < x1 < x3
    if y1 == y2:
        return y0 < y1 < y3
    for i in range(21):
        t = i / 20
        px, py = x1 + (x2 - x1) * t, y1 + (y2 - y1) * t
        if x0 < px < x3 and y0 < py < y3:
            return True
    return False


def analyze_schematic_text(text: str) -> LayoutQualityReport:
    """Analyze one emitted ``.kicad_sch`` document."""
    root = _parse(_tokenize(text))
    lib_boxes = _lib_symbol_bboxes(root)
    insts = _instance_bboxes(root, lib_boxes)
    segs = _wire_segments(root)

    overlaps: list[tuple[str, str, float]] = []
    for i in range(len(insts)):
        for j in range(i + 1, len(insts)):
            area = _overlap_area(insts[i][1], insts[j][1])
            if area > 0.01:
                overlaps.append((insts[i][0], insts[j][0], round(area, 2)))

    crossings = sum(1 for _ref, box in insts for s in segs if _seg_crosses_box(s, box))
    return LayoutQualityReport(
        symbols=len(insts),
        overlaps=overlaps,
        wire_body_crossings=crossings,
    )


def analyze_schematic_file(path: str | Path) -> LayoutQualityReport:
    """Analyze an emitted ``.kicad_sch`` file."""
    return analyze_schematic_text(Path(path).read_text(encoding="utf-8"))
