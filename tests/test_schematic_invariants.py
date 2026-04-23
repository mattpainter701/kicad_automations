"""Sprint 40 Task 170 + 174 — schematic emission invariants.

These invariants run on any .kicad_sch text and assert the generator never
ships structurally-broken output regardless of placer / topology dispatcher
bugs upstream:

1. No two symbol instances share ``(lib_id, ref, at x y rot)``.
2. No two symbol instances share a UUID.
3. No two wires share both endpoints.
4. No two global/hierarchical/sheet-local labels share
   ``(kind, text, at x y rot)``.
5. No two no-connects share ``(at x y)``.

The placer is free to get layout decisions wrong, but an internally
inconsistent schematic should never reach disk.
"""

from __future__ import annotations

import re
from pathlib import Path

# ---------------------------------------------------------------------------
# Invariant helpers (reused by the Sprint 40 corpus runner).
# ---------------------------------------------------------------------------


def _extract_symbol_instances(text: str) -> list[tuple[str, str, str, str]]:
    """Return (lib_id, reference, at, uuid) tuples for every placed symbol
    instance. Excludes lib_symbols entries (which live under ``(lib_symbols ...``).
    """
    instances = []
    depth = 0
    in_lib_symbols = False
    lib_depth = -1

    # Find start of the body — skip the lib_symbols block so we only see
    # placed instances.
    lib_start = text.find("(lib_symbols")
    body_start = 0
    if lib_start >= 0:
        depth_l = 0
        for i, ch in enumerate(text[lib_start:], start=lib_start):
            if ch == "(":
                depth_l += 1
            elif ch == ")":
                depth_l -= 1
                if depth_l == 0:
                    body_start = i + 1
                    break
    body = text[body_start:]

    for match in re.finditer(r'\(symbol\s+\(lib_id\s+"([^"]+)"\)\s+\(at\s+([^)]+)\)', body):
        lib_id = match.group(1)
        at = match.group(2).strip()
        # Look forward for ref + uuid in the same block
        block_start = match.start()
        sub = body[block_start : block_start + 2000]
        ref_match = re.search(r'\(property\s+"Reference"\s+"([^"]+)"', sub)
        uuid_match = re.search(r'\(uuid\s+"([^"]+)"', sub)
        instances.append(
            (
                lib_id,
                ref_match.group(1) if ref_match else "",
                at,
                uuid_match.group(1) if uuid_match else "",
            )
        )
    return instances


def _extract_wires(text: str) -> list[tuple[tuple[float, float], tuple[float, float]]]:
    wires = []
    for wire_match in re.finditer(r"\(wire\s+\(pts\s+(\(xy[^)]+\)\s*\(xy[^)]+\))", text):
        pts = re.findall(r"\(xy\s+([-0-9.eE]+)\s+([-0-9.eE]+)\)", wire_match.group(1))
        if len(pts) == 2:
            a = (round(float(pts[0][0]), 4), round(float(pts[0][1]), 4))
            b = (round(float(pts[1][0]), 4), round(float(pts[1][1]), 4))
            wires.append((a, b))
    return wires


def _extract_labels(text: str) -> list[tuple[str, str, str]]:
    labels = []
    for m in re.finditer(
        r'\((global_label|hierarchical_label|label)\s+"([^"]+)".*?\(at\s+([^)]+)\)',
        text,
        re.DOTALL,
    ):
        labels.append((m.group(1), m.group(2), m.group(3).strip()))
    return labels


def _extract_no_connects(text: str) -> list[str]:
    return [m.group(1).strip() for m in re.finditer(r"\(no_connect\s+\(at\s+([^)]+)\)", text)]


def assert_schematic_invariants(sch_text: str, *, context: str = "schematic") -> None:
    """Raise AssertionError with a specific, diff-friendly message on any
    duplicate element. Safe to reuse from the Sprint 40 corpus runner.
    """
    instances = _extract_symbol_instances(sch_text)

    # 1. (lib_id, ref, at) uniqueness
    seen_keys: dict[tuple[str, str, str], int] = {}
    for lib_id, ref, at, _uuid in instances:
        key = (lib_id, ref, at)
        seen_keys[key] = seen_keys.get(key, 0) + 1
    dup_keys = [k for k, n in seen_keys.items() if n > 1]
    assert not dup_keys, f"{context}: duplicate symbol instances (same lib_id+ref+at): {dup_keys}"

    # 2. UUID uniqueness
    seen_uuids: dict[str, int] = {}
    for _lib_id, _ref, _at, uuid in instances:
        if not uuid:
            continue
        seen_uuids[uuid] = seen_uuids.get(uuid, 0) + 1
    dup_uuids = [u for u, n in seen_uuids.items() if n > 1]
    assert not dup_uuids, f"{context}: duplicate symbol UUIDs: {dup_uuids}"

    # 3. Wire endpoints (order-insensitive)
    wires = _extract_wires(sch_text)
    seen_wire_keys: dict[tuple, int] = {}
    for a, b in wires:
        key_w = tuple(sorted([a, b]))
        seen_wire_keys[key_w] = seen_wire_keys.get(key_w, 0) + 1
    dup_wires = [w for w, n in seen_wire_keys.items() if n > 1]
    assert not dup_wires, f"{context}: duplicate wires: {dup_wires}"

    # 4. Label (kind, text, at) uniqueness
    labels = _extract_labels(sch_text)
    seen_lab_keys: dict[tuple[str, str, str], int] = {}
    for kind, txt, at in labels:
        seen_lab_keys[(kind, txt, at)] = seen_lab_keys.get((kind, txt, at), 0) + 1
    dup_labels = [k for k, n in seen_lab_keys.items() if n > 1]
    assert not dup_labels, f"{context}: duplicate labels: {dup_labels}"

    # 5. No-connect position uniqueness
    ncs = _extract_no_connects(sch_text)
    seen_nc: dict[str, int] = {}
    for pos in ncs:
        seen_nc[pos] = seen_nc.get(pos, 0) + 1
    dup_ncs = [p for p, n in seen_nc.items() if n > 1]
    assert not dup_ncs, f"{context}: duplicate no-connects: {dup_ncs}"


# ---------------------------------------------------------------------------
# Direct primitives test — ``assemble_sheet`` dedupes before emission.
# ---------------------------------------------------------------------------


def test_assemble_sheet_drops_duplicate_wires_and_labels():
    """The strap/support placer has been seen to add the same wire / global
    label twice (once via the passive-endpoint renderer, once via the shared
    anchor loop). ``assemble_sheet`` must dedupe these before emission so the
    on-disk schematic has a single wire / label per logical element.
    """
    from circuit_weaver.primitives import assemble_sheet

    header = '(kicad_sch (version 20231120) (generator "t")\n(uuid "a")\n(paper "A3")'
    instances = [
        '(symbol (lib_id "C_Small") (at 10 10 0) (unit 1)\n(property "Reference" "C1")\n(uuid "sym-c1-uuid"))',
        # Exact duplicate of the first (same UUID, same coord, same ref).
        '(symbol (lib_id "C_Small") (at 10 10 0) (unit 1)\n(property "Reference" "C1")\n(uuid "sym-c1-uuid"))',
        # Different ref at same coord — must be preserved (placer overlap, not
        # a duplicate instance).
        '(symbol (lib_id "C_Small") (at 10 10 0) (unit 1)\n(property "Reference" "C2")\n(uuid "sym-c2-uuid"))',
    ]
    wires = [
        '(wire (pts (xy 1 2) (xy 3 4)) (uuid "w1"))',
        # Duplicate with a different UUID must be collapsed.
        '(wire (pts (xy 1 2) (xy 3 4)) (uuid "w2"))',
        # Reversed endpoints are still the same wire.
        '(wire (pts (xy 3 4) (xy 1 2)) (uuid "w3"))',
    ]
    labels = [
        '(global_label "VBAT" (shape bidirectional) (at 5 6 180) (uuid "l1"))',
        '(global_label "VBAT" (shape bidirectional) (at 5 6 180) (uuid "l2"))',
    ]
    no_connects = [
        '(no_connect (at 7 8) (uuid "nc1"))',
        '(no_connect (at 7 8) (uuid "nc2"))',
    ]

    sch = assemble_sheet(
        header,
        lib_symbols=[],
        instances=instances,
        labels=labels,
        no_connects=no_connects,
        wires=wires,
    )

    # Parsed invariants
    assert_schematic_invariants(sch, context="assemble_sheet dedup")

    # And a specific structural count: after dedup we expect exactly two
    # symbol instances (C1 and C2), one wire, one label, one NC.
    instances_out = _extract_symbol_instances(sch)
    assert {ref for _lib, ref, _at, _uuid in instances_out} == {"C1", "C2"}
    assert len(_extract_wires(sch)) == 1
    assert len(_extract_labels(sch)) == 1
    assert len(_extract_no_connects(sch)) == 1


def test_user_reported_schematic_invariant_would_fail_before_fix(tmp_path: Path):
    """The Sprint 40 audit shipped a real example that exhibits every
    double-emission symptom. Build a minimal reproducer and prove the
    invariant runner catches it. If this test ever starts passing for a
    known-bad input, the invariant is broken.
    """
    bad_sch = """
(kicad_sch (version 20231120)
(lib_symbols)
(symbol (lib_id "C_Review") (at 228.60 102.87 180) (unit 1)
  (property "Reference" "C2") (uuid "dup-uuid-1"))
(symbol (lib_id "C_Review") (at 228.60 102.87 180) (unit 1)
  (property "Reference" "C2") (uuid "dup-uuid-2"))
(wire (pts (xy 233.68 102.87) (xy 240.03 102.87)) (uuid "w-a"))
(wire (pts (xy 233.68 102.87) (xy 240.03 102.87)) (uuid "w-b"))
(global_label "VBAT" (shape bidirectional) (at 240.03 102.87 180) (uuid "la"))
(global_label "VBAT" (shape bidirectional) (at 240.03 102.87 180) (uuid "lb"))
)
""".strip()

    try:
        assert_schematic_invariants(bad_sch, context="reproducer")
    except AssertionError as exc:
        msg = str(exc)
        assert "duplicate symbol instances" in msg or "duplicate wires" in msg or "duplicate labels" in msg
    else:
        raise AssertionError(
            "invariant runner failed to detect the Sprint 40 reproducer — Task 170 regression gate is broken"
        )
