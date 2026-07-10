"""Sprint 40 Task 171 — placement PCB preview invariants.

The placement ``.kicad_pcb`` is a layout hint produced alongside the
schematic, not a fabrication-ready board. Previously the generator:

* fell back to ``Package_SO:SOIC-8_3.9x4.9mm_P1.27mm`` whenever a
  component lacked a ``footprint`` binding, producing physically-wrong
  geometry (an ESP32 module with a SOIC-8 outline, a tactile switch with
  a SOIC-8 outline, etc.), and
* synthesized two 1.27-pitch SMD pads for every footprint regardless of
  the real pad count, so modules with ~41 pads shipped with 2.

Both behaviors looked plausible enough to pass visual review and burned
users who tried to fab the file directly. The current policy:

* Real footprint bindings pass through unchanged.
* Missing footprints get a clearly-labelled placeholder
  (``Placement_Preview:Missing_<ref>``) that can't be mistaken for a
  fabricatable part.
* No synthetic pads are ever emitted — KiCad's schematic → PCB forward
  annotation is the authoritative source of pads.

These tests lock in the policy so the next wave of PCB work can't
silently reintroduce fabricated geometry.
"""

from __future__ import annotations

import re

from circuit_weaver.component_db import ComponentDef, PinDef


def _make_component(
    *,
    mpn: str,
    ref: str,
    footprint: str,
    pin_count: int,
    category: str = "digital",
    ref_prefix: str = "U",
) -> ComponentDef:
    pins = [PinDef(str(i), f"P{i}", "passive", "L" if i % 2 else "R") for i in range(1, pin_count + 1)]
    return ComponentDef(
        mpn=mpn,
        ref_prefix=ref_prefix,
        value=mpn,
        footprint=footprint,
        description="",
        category=category,
        source_ref=ref,
        pins=pins,
        power_pins={},
        pin_nets={},
    )


def _extract_footprint_blocks(pcb_text: str) -> list[str]:
    """Return the text of each top-level ``(footprint ...)`` block."""
    blocks = []
    depth = 0
    start = -1
    i = 0
    while i < len(pcb_text):
        if pcb_text[i : i + len("(footprint")] == "(footprint" and depth == 0:
            start = i
            depth = 1
            i += len("(footprint")
            continue
        if start >= 0:
            ch = pcb_text[i]
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0:
                    blocks.append(pcb_text[start : i + 1])
                    start = -1
        i += 1
    return blocks


def _count_pads(footprint_block: str) -> int:
    return len(re.findall(r"\(pad\s", footprint_block))


def test_preview_pcb_never_fabricates_soic8_fallback(tmp_path):
    """A component with no ``footprint`` binding MUST NOT get a SOIC-8
    fallback. It gets a ``Placement_Preview:Missing_<ref>`` placeholder,
    which is impossible to mistake for a real part.
    """
    from circuit_weaver.pcb_export import generate_pcb_placement

    comps = [
        _make_component(mpn="UNBOUND-1", ref="U1", footprint="", pin_count=8, category="sensor"),
        _make_component(mpn="UNBOUND-2", ref="LED1", footprint="", pin_count=2, category="digital", ref_prefix="D"),
    ]
    pcb_file, _placements = generate_pcb_placement(comps, tmp_path, project_name="preview_test")

    assert pcb_file == str(tmp_path / "preview_test_placement_preview.kicad_pcb")
    pcb_text = (tmp_path / "preview_test_placement_preview.kicad_pcb").read_text(encoding="utf-8")

    assert "Package_SO:SOIC-8_3.9x4.9mm_P1.27mm" not in pcb_text, (
        "preview PCB must never fall back to the SOIC-8 default when a component has no footprint binding"
    )
    # Each unbound component gets a clearly-labeled placeholder.
    assert "Placement_Preview:Missing_U1" in pcb_text
    assert "Placement_Preview:Missing_LED1" in pcb_text


def test_preview_pcb_never_emits_synthetic_pads(tmp_path):
    """No footprint block in the preview PCB may contain ``(pad ...)`` —
    the synthesized 2-pad fallback has caused modules with 40+ real pads
    to be rendered with 2, hiding pin-to-pad assignment errors.
    """
    from circuit_weaver.pcb_export import generate_pcb_placement

    comps = [
        _make_component(
            mpn="ESP32-S3-WROOM-1",
            ref="U1",
            footprint="RF_Module:ESP32-S3-WROOM-1",
            pin_count=41,
            category="digital",
        ),
        _make_component(
            mpn="BME688",
            ref="U2",
            footprint="Package_LGA:LGA-8_3.0x3.0mm_P0.8mm",
            pin_count=8,
            category="sensor",
        ),
        _make_component(
            mpn="BARREL_JACK",
            ref="J1",
            footprint="Connector_BarrelJack:BarrelJack_Horizontal",
            pin_count=3,
            category="connector",
            ref_prefix="J",
        ),
        _make_component(
            mpn="NO-BIND",
            ref="SW1",
            footprint="",
            pin_count=2,
            category="digital",
            ref_prefix="SW",
        ),
    ]
    pcb_file, _placements = generate_pcb_placement(comps, tmp_path, project_name="preview_test")

    assert pcb_file == str(tmp_path / "preview_test_placement_preview.kicad_pcb")
    pcb_text = (tmp_path / "preview_test_placement_preview.kicad_pcb").read_text(encoding="utf-8")

    fp_blocks = _extract_footprint_blocks(pcb_text)
    assert fp_blocks, "generator emitted no footprint blocks at all"
    for block in fp_blocks:
        n_pads = _count_pads(block)
        assert n_pads == 0, (
            f"preview PCB footprint emitted {n_pads} synthetic pad(s); "
            f"no pads may be fabricated here. Block starts: {block[:100]!r}"
        )


def test_preview_pcb_self_identifies_in_generator_field(tmp_path):
    """The ``(generator ...)`` field must mark this file as a placement
    preview so downstream tooling / users can't mistake it for a
    fabrication-ready board.
    """
    from circuit_weaver.pcb_export import generate_pcb_placement

    comps = [_make_component(mpn="X", ref="U1", footprint="Package_SO:SOIC-8_3.9x4.9mm_P1.27mm", pin_count=8)]
    pcb_file, _placements = generate_pcb_placement(comps, tmp_path, project_name="ident_test")
    assert pcb_file.endswith("ident_test_placement_preview.kicad_pcb")
    pcb_text = (tmp_path / "ident_test_placement_preview.kicad_pcb").read_text(encoding="utf-8")
    assert "placement_preview" in pcb_text, (
        "placement .kicad_pcb must self-identify as a preview in the generator field"
    )


def test_preview_pcb_uses_kicad_fixed_layer_ids(tmp_path):
    """The preview board must use KiCad's fixed 2-layer hash, not the
    legacy KiCad-5-era table. The old table used ``B.Cu=31`` and
    ``ECO1.User``/``ECO2.User``, which KiCad 10 rejects with a
    ``not fixed layer hash`` error when opening the placement board.
    """
    from circuit_weaver.pcb_export import generate_pcb_placement

    comps = [_make_component(mpn="X", ref="U1", footprint="Package_SO:SOIC-8_3.9x4.9mm_P1.27mm", pin_count=8)]
    generate_pcb_placement(comps, tmp_path, project_name="layer_hash_test")
    pcb_text = (tmp_path / "layer_hash_test_placement_preview.kicad_pcb").read_text(encoding="utf-8")

    expected_markers = [
        '(0 "F.Cu" signal)',
        '(2 "B.Cu" signal)',
        '(9 "F.Adhes" user "F.Adhesive")',
        '(11 "B.Adhes" user "B.Adhesive")',
        '(13 "F.Paste" user)',
        '(15 "B.Paste" user)',
        '(5 "F.SilkS" user "F.Silkscreen")',
        '(7 "B.SilkS" user "B.Silkscreen")',
        '(1 "F.Mask" user)',
        '(3 "B.Mask" user)',
        '(17 "Dwgs.User" user "User.Drawings")',
        '(19 "Cmts.User" user "User.Comments")',
        '(21 "Eco1.User" user "User.Eco1")',
        '(23 "Eco2.User" user "User.Eco2")',
        '(25 "Edge.Cuts" user)',
        '(27 "Margin" user)',
        '(31 "F.CrtYd" user "F.Courtyard")',
        '(29 "B.CrtYd" user "B.Courtyard")',
        '(35 "F.Fab" user)',
        '(33 "B.Fab" user)',
        '(39 "User.1" user)',
        '(41 "User.2" user)',
        '(43 "User.3" user)',
        '(45 "User.4" user)',
    ]
    for marker in expected_markers:
        assert marker in pcb_text, f"missing KiCad fixed-layer marker: {marker}"

    assert '(31 "B.Cu" signal)' not in pcb_text
    assert "ECO1.User" not in pcb_text
    assert "ECO2.User" not in pcb_text
