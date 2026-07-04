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

import subprocess
import sys
from pathlib import Path

import pytest

from circuit_weaver.layout_quality import analyze_schematic_file

SAMPLES_DIR = Path(__file__).resolve().parent.parent / "samples"

# Ceilings reflect the current known-remaining crossings. Body-aware stub
# lengths plus tap-splitting detours (T236) drove all three samples to zero;
# never raise these.
QUALITY_SAMPLES = {
    "motor_controller": 0,
    "oled_display_module": 0,
    "usb_regulated_supply": 0,
}


def _analyze(sch_path: Path) -> dict:
    report = analyze_schematic_file(sch_path)
    return {
        "overlaps": report.overlaps,
        "wire_body_crossings": report.wire_body_crossings,
        "symbols": report.symbols,
    }


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
    from circuit_weaver.primitives import sexpr_wire, snap

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


def _wire_segs(wires):
    from circuit_weaver.generator import _WIRE_PTS_RE

    segs = []
    for w in wires:
        m = _WIRE_PTS_RE.search(w)
        if m:
            segs.append(tuple(float(m.group(i)) for i in range(1, 5)))
    return segs


def test_detour_pass_preserves_tapped_junction_points():
    """Splitting a tapped trunk must keep every tap point as a piece endpoint.

    A tap landing inside a body cannot be detoured away from — the pieces on
    either side keep their original geometry, so the junction stays intact.
    """
    from circuit_weaver.generator import _detour_wires_around_bodies
    from circuit_weaver.primitives import sexpr_wire

    body = (96.6, 101.0, 106.6, 111.0)
    trunk = sexpr_wire(101.6, 96.52, 101.6, 116.84)
    tap = sexpr_wire(101.6, 106.68, 121.92, 106.68)  # taps the trunk mid-run, inside the body
    out = _detour_wires_around_bodies([trunk, tap], [body])
    segs = _wire_segs(out)
    endpoints = {(x1, y1) for x1, y1, _x2, _y2 in segs} | {(x2, y2) for _x1, _y1, x2, y2 in segs}
    # The tap point and both trunk ends survive as wire endpoints.
    assert (101.6, 106.68) in endpoints
    assert (101.6, 96.52) in endpoints
    assert (101.6, 116.84) in endpoints
    # Trunk coverage along x=101.6 is unbroken from 96.52 to 116.84.
    vertical = sorted((min(y1, y2), max(y1, y2)) for x1, y1, x2, y2 in segs if x1 == x2 == 101.6)
    reach = 96.52
    for lo, hi in vertical:
        assert lo <= reach + 0.01
        reach = max(reach, hi)
    assert reach == pytest.approx(116.84)


def test_detour_pass_reroutes_tapped_trunk_around_body():
    """A multi-tap rail crossing a body is split at its taps and the crossing
    piece is rerouted while every junction point survives as an endpoint."""
    from circuit_weaver.generator import _detour_wires_around_bodies, _segment_hits_box
    from circuit_weaver.primitives import sexpr_wire

    body = (96.6, 101.6, 106.6, 111.6)
    # Trunk crosses the body between its two taps; taps sit outside the body.
    trunk = sexpr_wire(101.6, 91.44, 101.6, 121.92)
    tap_above = sexpr_wire(101.6, 96.52, 121.92, 96.52)
    tap_below = sexpr_wire(101.6, 116.84, 121.92, 116.84)
    out = _detour_wires_around_bodies([trunk, tap_above, tap_below], [body])
    segs = _wire_segs(out)
    assert all(not _segment_hits_box(x1, y1, x2, y2, body) for x1, y1, x2, y2 in segs), (
        f"a segment still crosses the body: {segs}"
    )
    endpoints = {(x1, y1) for x1, y1, _x2, _y2 in segs} | {(x2, y2) for _x1, _y1, x2, y2 in segs}
    for junction in [(101.6, 96.52), (101.6, 116.84), (101.6, 91.44), (101.6, 121.92)]:
        assert junction in endpoints, f"junction {junction} lost by the tap-splitting detour"


def test_clear_stub_length_avoids_foreign_body():
    """Stub endpoints and their marker glyphs must clear neighboring bodies."""
    from circuit_weaver.generator import _clear_stub_length, _stub_endpoint, _stub_marker_clear

    # A passive body sits 4mm above the pin; the requested stub would land
    # the marker inside it.
    pin = (100.0, 120.0)
    body = (98.0, 112.0, 102.0, 116.0)
    desired = 6.35  # endpoint at y=113.65, inside the body
    picked = _clear_stub_length(pin[0], pin[1], 270, desired, [body])
    assert picked != desired
    assert _stub_marker_clear(pin[0], pin[1], 270, picked, [body])
    wx, wy = _stub_endpoint(pin[0], pin[1], 270, picked)
    assert not (body[0] < wx < body[2] and body[1] < wy < body[3])


def test_clear_stub_length_keeps_clear_default():
    """When the requested stub is already clear it is returned unchanged."""
    from circuit_weaver.generator import _clear_stub_length

    assert _clear_stub_length(100.0, 120.0, 270, 2.54, [(200.0, 200.0, 210.0, 210.0)]) == 2.54
    assert _clear_stub_length(100.0, 120.0, 270, 2.54, []) == 2.54
