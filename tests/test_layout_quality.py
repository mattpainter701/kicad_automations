"""Schematic layout quality gates.

Parses generated .kicad_sch output geometrically and asserts the layout
invariants that made generated schematics read as sloppy when violated:

- no two symbol bodies may overlap (support passives used to stack at
  identical coordinates when their owner pins resolved to one point);
- wire segments crossing symbol body interiors stay under a per-sample
  ceiling (long "local" wires used to slice straight through IC and
  passive bodies).

The parser here is deliberately independent of the generator: it reads the
emitted S-expressions the way KiCad would, so regressions in any placement
or routing pass surface regardless of which pass caused them.
"""

from __future__ import annotations

import math
import re
import subprocess
import sys
from pathlib import Path

import pytest

SAMPLES_DIR = Path(__file__).resolve().parent.parent / "samples"

# Ceilings reflect the current known-remaining crossings (mostly wires
# terminating on anchors adjacent to cap bodies). Lower them as the
# remaining cluster passes become occupancy-aware; never raise them.
QUALITY_SAMPLES = {
    "motor_controller": 4,
    "oled_display_module": 10,
    "usb_regulated_supply": 5,
}


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


def _instance_bboxes(root, lib_boxes):
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


def _wire_segments(root):
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


def _analyze(sch_path: Path) -> dict:
    root = _parse(_tokenize(sch_path.read_text(encoding="utf-8")))
    lib_boxes = _lib_symbol_bboxes(root)
    insts = _instance_bboxes(root, lib_boxes)
    segs = _wire_segments(root)

    overlaps = []
    for i in range(len(insts)):
        for j in range(i + 1, len(insts)):
            area = _overlap_area(insts[i][1], insts[j][1])
            if area > 0.01:
                overlaps.append((insts[i][0], insts[j][0], round(area, 2)))

    crossings = sum(1 for _ref, box in insts for s in segs if _seg_crosses_box(s, box))
    return {"overlaps": overlaps, "wire_body_crossings": crossings, "symbols": len(insts)}


@pytest.fixture(scope="module")
def generated_samples(tmp_path_factory):
    """Generate the quality-gated samples once for the whole module."""
    out: dict[str, Path] = {}
    base = tmp_path_factory.mktemp("layout_quality")
    for name in QUALITY_SAMPLES:
        spec = SAMPLES_DIR / name / f"{name}.yaml"
        target = base / name
        result = subprocess.run(
            [sys.executable, "-m", "circuit_weaver", "generate", str(spec), "--output", str(target)],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"generate failed for {name}: {result.stderr[:500]}"
        sch_files = list(target.glob("*.kicad_sch"))
        assert sch_files, f"no .kicad_sch emitted for {name}"
        out[name] = sch_files[0]
    return out


@pytest.mark.parametrize("sample", sorted(QUALITY_SAMPLES))
def test_no_symbol_body_overlaps(generated_samples, sample):
    """No two placed symbol bodies may overlap — stacked passives are the
    canonical 'sloppy generated schematic' failure."""
    report = _analyze(generated_samples[sample])
    assert report["overlaps"] == [], f"{sample}: overlapping symbol bodies {report['overlaps']}"


@pytest.mark.parametrize("sample", sorted(QUALITY_SAMPLES))
def test_wire_body_crossings_within_ceiling(generated_samples, sample):
    """Wires slicing through symbol bodies stay under the recorded ceiling."""
    report = _analyze(generated_samples[sample])
    ceiling = QUALITY_SAMPLES[sample]
    assert report["wire_body_crossings"] <= ceiling, (
        f"{sample}: {report['wire_body_crossings']} wire segments cross symbol bodies "
        f"(ceiling {ceiling}) — a placement or routing pass regressed"
    )


def test_sidecar_passives_never_share_coordinates():
    """Direct regression for the stacked-sidecar bug: passives whose owner
    pins resolve to the same parent-pin point must fan out, not stack."""
    from circuit_weaver.placer import _apply_topology_sidecar_cluster

    class _FakePassive:
        def __init__(self, ref, role, owner_pin, net1):
            self.ref = ref
            self.role = role
            self.owner_pin = owner_pin
            self.net1 = net1
            self.x = 0.0
            self.y = 0.0
            self.angle = 0

    class _FakePC:
        ref = "U1"

    import circuit_weaver.placer as placer_mod

    pin_point = (100.0, 50.0, 0)
    orig_pin_point = placer_mod._parent_pin_point
    orig_side = placer_mod._passive_pin_side
    placer_mod._parent_pin_point = lambda pc, owner, net: pin_point
    placer_mod._passive_pin_side = lambda pc, pt: "left"
    try:
        passives = [
            _FakePassive("C1", "decoupling", "CVDD", "VDD"),
            _FakePassive("C2", "bulk_cap", "CVDD_BULK", "VDD"),
            _FakePassive("R1", "reset_pullup", "RRES", "RES_N"),
        ]
        processed = _apply_topology_sidecar_cluster(None, _FakePC(), passives, [])
        assert processed == {"C1", "C2", "R1"}
        poses = {(pp.x, pp.y) for pp in passives}
        assert len(poses) == 3, f"sidecar passives stacked: {[(pp.ref, pp.x, pp.y) for pp in passives]}"
        for a in passives:
            for b in passives:
                if a.ref >= b.ref:
                    continue
                assert abs(a.x - b.x) >= 7.62 or abs(a.y - b.y) >= 7.62
    finally:
        placer_mod._parent_pin_point = orig_pin_point
        placer_mod._passive_pin_side = orig_side


def test_passive_pin_side_uses_pin_angle():
    """Pin angle is authoritative for face detection — a top-face pin near
    the body's left corner must not be classified 'left'."""
    from circuit_weaver.placer import _passive_pin_side

    class _FakePC:
        pass

    # angle 270 = pin points down into the body = top face,
    # even though the coordinates sit near the left edge.
    assert _passive_pin_side(_FakePC(), (45.72, 50.8, 270)) == "top"
    assert _passive_pin_side(_FakePC(), (38.1, 60.96, 0)) == "left"
    assert _passive_pin_side(_FakePC(), (73.66, 58.42, 180)) == "right"
    assert _passive_pin_side(_FakePC(), (50.0, 90.0, 90)) == "bottom"


def test_local_anchor_beyond_budget_falls_back_to_labels():
    """Anchors farther than the local-wire budget must be ignored so the
    generator emits net labels instead of cross-sheet wires."""
    from circuit_weaver.generator import _nearest_local_anchor

    class _Anchor:
        def __init__(self, name, x, y):
            self.name = name
            self.x = x
            self.y = y

    class _Layout:
        def __init__(self, anchors):
            self.local_net_anchors = anchors

    near = _Anchor("VDD", 110.0, 100.0)
    far = _Anchor("VDD", 300.0, 100.0)
    assert _nearest_local_anchor(_Layout([near]), "VDD", 100.0, 100.0) is near
    assert _nearest_local_anchor(_Layout([far]), "VDD", 100.0, 100.0) is None


def test_route_local_connection_detours_around_sibling_bodies():
    """A route blocked by a sibling passive body must bend around it."""
    from circuit_weaver.generator import _WIRE_PTS_RE, _route_local_connection

    wires: list[str] = []
    sibling = (98.0, 104.0, 102.0, 108.0)  # straddles the straight path
    _route_local_connection(100.0, 100.0, 100.0, 112.0, wires, obstacles=[sibling])
    assert wires, "route emitted no wires"
    for w in wires:
        m = _WIRE_PTS_RE.search(w)
        assert m, w
        x1, y1, x2, y2 = (float(m.group(i)) for i in range(1, 5))
        # No segment may pass through the sibling body interior.
        if abs(x1 - x2) < 0.01 and sibling[0] < x1 < sibling[2]:
            assert not (max(min(y1, y2), sibling[1]) < min(max(y1, y2), sibling[3]))
        if abs(y1 - y2) < 0.01 and sibling[1] < y1 < sibling[3]:
            assert not (max(min(x1, x2), sibling[0]) < min(max(x1, x2), sibling[2]))


def test_decoupling_bank_walks_away_from_occupied_anchor():
    """Decoupling banks reserve anchors/passive bodies before selecting the next bank."""
    from circuit_weaver.component_db import ComponentDef
    from circuit_weaver.placer import (
        PlacedComponent,
        PlacedPassive,
        SheetLayout,
        _apply_topology_decoupling_bank,
    )

    pc = PlacedComponent(ComponentDef(mpn="U", value="U"), "U1", 100.0, 100.0)
    passives = [
        PlacedPassive("C1", "100n", "", 0, 0, "VDD", "GND", "C", parent_ref="U1", role="decoupling"),
        PlacedPassive("C2", "100n", "", 0, 0, "VDD", "GND", "C", parent_ref="U1", role="decoupling"),
        PlacedPassive("C3", "100n", "", 0, 0, "AVDD", "GND", "C", parent_ref="U1", role="decoupling"),
        PlacedPassive("C4", "100n", "", 0, 0, "AVDD", "GND", "C", parent_ref="U1", role="decoupling"),
    ]
    layout = SheetLayout("s", "s", "A4", placed_ics=[pc], placed_passives=passives)
    occupied: list[tuple[float, float]] = []

    assert _apply_topology_decoupling_bank(layout, pc, passives, occupied) == {"C1", "C2", "C3", "C4"}

    first_bank = [(pp.x, pp.y) for pp in passives[:2]] + [(a.x, a.y) for a in layout.local_net_anchors[:2]]
    second_bank = [(pp.x, pp.y) for pp in passives[2:]] + [(a.x, a.y) for a in layout.local_net_anchors[2:]]
    for x1, y1 in first_bank:
        for x2, y2 in second_bank:
            assert abs(x1 - x2) >= 7.62 or abs(y1 - y2) >= 7.62


def test_ldo_cluster_respects_preoccupied_topology_slot():
    """LDO cluster placement walks when its preferred cap/anchor positions are reserved."""
    from circuit_weaver.component_db import ComponentDef
    from circuit_weaver.placer import PlacedComponent, PlacedPassive, SheetLayout, _apply_topology_ldo_cluster

    pc = PlacedComponent(ComponentDef(mpn="LDO", value="LDO", category="power"), "U1", 100.0, 100.0)
    caps = [
        PlacedPassive("CIN", "1u", "", 0, 0, "VIN", "GND", "C", parent_ref="U1", owner_pin="IN", role="decoupling"),
        PlacedPassive("COUT", "1u", "", 0, 0, "VOUT", "GND", "C", parent_ref="U1", owner_pin="OUT", role="decoupling"),
    ]
    layout = SheetLayout("s", "s", "A4", placed_ics=[pc], placed_passives=caps)
    # Reserve the preferred CIN center for a zero-pin generic symbol at (100,100):
    # center_x=100, cluster_y=110.16, CIN x=93.65.
    occupied = [(93.65, 110.16)]

    assert _apply_topology_ldo_cluster(layout, pc, caps, occupied) == {"CIN", "COUT"}
    assert (caps[0].x, caps[0].y) != (93.65, 110.16)
    assert all(abs(caps[0].x - x) >= 7.62 or abs(caps[0].y - y) >= 7.62 for x, y in [(93.65, 110.16)])


def test_occupancy_reservation_deduplicates_anchor_points():
    """Repeated cluster/anchor reservations must not bloat the shared occupancy list."""
    from circuit_weaver.placer import _reserve_occupancy

    occupied: list[tuple[float, float]] = []
    _reserve_occupancy(occupied, (10.0, 20.0), (10.0, 20.0))
    _reserve_occupancy(occupied, (10.0, 20.0))

    assert occupied == [(10.16, 20.32)]


def test_detour_wires_around_bodies_rewrites_through_segments():
    """The final hygiene pass reroutes a wire crossing a symbol body."""
    from circuit_weaver.generator import _WIRE_PTS_RE, _detour_wires_around_bodies
    from circuit_weaver.primitives import snap, sexpr_wire

    body = (95.0, 100.0, 105.0, 110.0)
    start = (snap(100.0), snap(95.0))
    end = (snap(100.0), snap(115.0))
    wires = [sexpr_wire(start[0], start[1], end[0], end[1])]
    out = _detour_wires_around_bodies(wires, [body])
    assert len(out) == 3, "expected the through-wire to become a 3-segment detour"
    endpoints = []
    for w in out:
        m = _WIRE_PTS_RE.search(w)
        x1, y1, x2, y2 = (float(m.group(i)) for i in range(1, 5))
        endpoints.append(((x1, y1), (x2, y2)))
        if abs(x1 - x2) < 0.01 and body[0] < x1 < body[2]:
            assert not (max(min(y1, y2), body[1]) < min(max(y1, y2), body[3]))
    assert endpoints[0][0] == pytest.approx(start, abs=0.01)
    assert endpoints[-1][1] == pytest.approx(end, abs=0.01)


def test_detour_pass_preserves_tapped_segments():
    """Segments with a T-joint on their interior must not be rerouted."""
    from circuit_weaver.generator import _detour_wires_around_bodies
    from circuit_weaver.primitives import sexpr_wire

    body = (95.0, 100.0, 105.0, 110.0)
    trunk = sexpr_wire(100.0, 95.0, 100.0, 115.0)
    tap = sexpr_wire(100.0, 105.0, 120.0, 105.0)  # taps the trunk mid-run
    out = _detour_wires_around_bodies([trunk, tap], [body])
    assert trunk in out, "tapped trunk wire must be left untouched"
    assert tap in out
