"""Tests for JLCPCB export helpers."""

from __future__ import annotations

import csv
import json
import os
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from circuit_weaver.assembly_manifest import AssemblyItem
from circuit_weaver.component_db import BypassCap, ComponentDef
from circuit_weaver.jlcpcb_export import (
    CplSourceError,
    _detect_price_breaks,
    _publish_delivery_staging,
    export_jlcpcb,
    generate_assembly_variants,
    group_bom_rows,
    parse_pcb_placements,
    write_jlcpcb_bom,
    write_jlcpcb_cpl,
)


def _comp(ref: str, value: str = "10k", footprint: str = "Resistor_SMD:R_0402", lcsc: str = "C1"):
    return ComponentDef(
        mpn=value,
        value=value,
        footprint=footprint,
        lcsc_pn=lcsc,
        source_ref=ref,
    )


def test_group_bom_rows_groups_by_value_footprint_and_lcsc():
    rows = group_bom_rows([
        _comp("R1", "10k", "Resistor_SMD:R_0402", "C25744"),
        _comp("R2", "10k", "Resistor_SMD:R_0402", "C25744"),
        _comp("C1", "100nF", "Capacitor_SMD:C_0402", "C1525"),
    ])

    assert len(rows) == 2
    resistor = next(row for row in rows if row["comment"] == "10k")
    assert resistor["designators"] == "R1,R2"
    assert resistor["footprint"] == "R_0402"
    assert resistor["has_lcsc"] is True


def test_group_bom_rows_does_not_merge_same_value_footprint_with_incompatible_mpns():
    rows = group_bom_rows(
        [
            AssemblyItem(
                reference="U1",
                value="3.3V regulator",
                footprint="Package_TO_SOT_SMD:SOT-23-5",
                mpn="REG-A-33",
                manufacturer="Alpha",
            ),
            AssemblyItem(
                reference="U2",
                value="3.3V regulator",
                footprint="Package_TO_SOT_SMD:SOT-23-5",
                mpn="REG-B-33",
                manufacturer="Beta",
            ),
        ]
    )

    assert len(rows) == 2
    assert {row["designators"] for row in rows} == {"U1", "U2"}


def test_write_jlcpcb_bom_quotes_grouped_designators_as_one_csv_field(tmp_path):
    path = tmp_path / "bom.csv"
    rows = group_bom_rows([_comp("R1"), _comp("R2")])

    write_jlcpcb_bom(rows, path)

    with path.open(newline="", encoding="utf-8") as handle:
        parsed = list(csv.reader(handle))
    assert parsed[0] == ["Comment", "Designator", "Footprint", "LCSC Part#"]
    assert len(parsed[1]) == 4
    assert parsed[1][1] == "R1,R2"


def test_write_jlcpcb_cpl_uses_top_bottom_layer_names(tmp_path):
    path = tmp_path / "cpl.csv"
    comps = [_comp("U1"), _comp("U2")]
    placements = {"U1": (1.0, 2.0, 90.0, "top"), "U2": (3.0, 4.0, 180.0, "bottom")}

    write_jlcpcb_cpl(comps, placements, path)

    text = path.read_text(encoding="utf-8")
    assert "U1,1.00,2.00,90.0,top" in text
    assert "U2,3.00,4.00,180.0,bottom" in text


def _write_real_pcb(path, refs=("R1", "R2")):
    footprints = []
    for index, ref in enumerate(refs):
        layer = "F.Cu" if index % 2 == 0 else "B.Cu"
        footprints.append(
            f'''  (footprint "Resistor_SMD:R_0402"
    (layer "{layer}")
    (at {12.5 + index} {23.0 + index} {90 * index})
    (property "Reference" "{ref}" (at 0 0 0))
    (pad "1" smd roundrect (at 0 0) (size 1 1) (layers "F.Cu" "F.Paste" "F.Mask"))
  )'''
        )
    path.write_text(
        '(kicad_pcb (version 20240108) (generator "pcbnew")\n'
        '  (setup (aux_axis_origin 10 20))\n'
        + "\n".join(footprints)
        + "\n)\n",
        encoding="utf-8",
    )


def test_parse_pcb_placements_requires_real_pads_and_applies_aux_origin(tmp_path):
    board = tmp_path / "real.kicad_pcb"
    _write_real_pcb(board)

    placements = parse_pcb_placements(board, required_refs={"R1", "R2"})

    assert placements["R1"] == (2.5, 3.0, 0.0, "top")
    assert placements["R2"] == (3.5, 4.0, 90.0, "bottom")


def test_parse_pcb_placements_rejects_stale_footprint_identity(tmp_path):
    board = tmp_path / "stale.kicad_pcb"
    _write_real_pcb(board, refs=("U1",))

    with pytest.raises(CplSourceError, match="footprint identity mismatch.*U1"):
        parse_pcb_placements(
            board,
            required_refs={"U1"},
            expected_footprints={"U1": "Package_QFN:QFN-48"},
        )


def test_parse_pcb_placements_rejects_unexpected_pad_bearing_assembly_refs(tmp_path):
    board = tmp_path / "extra_ref.kicad_pcb"
    _write_real_pcb(board, refs=("R1", "R2"))

    with pytest.raises(CplSourceError, match="unexpected.*R2"):
        parse_pcb_placements(board, required_refs={"R1"})


@pytest.mark.parametrize("generator", ["schematic_engine placement_preview", "pcbnew"])
def test_parse_pcb_placements_rejects_preview_or_padless_board(tmp_path, generator):
    board = tmp_path / "blocked.kicad_pcb"
    board.write_text(
        f'''(kicad_pcb (version 20240108) (generator "{generator}")
  (footprint "Package:Part" (layer "F.Cu") (at 1 2)
    (property "Reference" "U1" (at 0 0 0))
  )
)''',
        encoding="utf-8",
    )
    expected = "Placement preview" if "preview" in generator else "no pad-bearing"
    with pytest.raises(CplSourceError, match=expected):
        parse_pcb_placements(board)


def test_detect_price_breaks_flags_twenty_percent_savings():
    rows = [{"designators": "R1,R2", "lcsc_pn": "C25744"}]
    with patch("circuit_weaver.parts_lookup.PartsLookup") as mock_lookup:
        mock_lookup.return_value.lookup_by_lcsc.return_value = {
            "prices": {"1": "$0.100", "10": "$0.090", "100": "$0.070"}
        }

        alerts = _detect_price_breaks(rows)

    assert len(alerts) == 1
    assert alerts[0]["lcsc_pn"] == "C25744"
    assert alerts[0]["savings_pct_100"] == 30.0


def test_generate_assembly_variants_default_includes_all_source_refs():
    comps = [_comp("R1"), _comp("R2"), ComponentDef(mpn="NOREF")]

    variants = generate_assembly_variants(comps)

    assert len(variants) == 1
    assert variants[0]["name"] == "default"
    assert variants[0]["included_refs"] == ["R1", "R2", "U1"]
    assert len(variants[0]["components"]) == 3


def test_generate_assembly_variants_respects_include_exclude_and_dnp_refs():
    comps = [_comp("R1"), _comp("R2"), _comp("R3")]

    variants = generate_assembly_variants(
        comps,
        [{"name": "No Sensor", "include_refs": ["R1", "R2", "R3"], "exclude_refs": ["R2"], "dnp_refs": ["R3"]}],
    )

    variant = variants[0]
    assert variant["token"] == "no_sensor"
    assert variant["included_refs"] == ["R1"]
    assert variant["dnp_refs"] == ["R3"]
    assert set(variant["omitted_refs"]) == {"R2", "R3"}


def test_generate_assembly_variants_keep_support_parts_with_owner():
    owner = _comp("U1", value="CTRL", footprint="Package_QFN:QFN-8")
    owner.bypass_caps = [
        BypassCap("1", "VDD", "GND", "100nF", "Capacitor_SMD:C_0402")
    ]

    included = generate_assembly_variants(
        [owner],
        [{"name": "controller", "include_refs": ["U1"]}],
    )[0]
    excluded = generate_assembly_variants(
        [owner],
        [{"name": "no-controller", "exclude_refs": ["U1"]}],
    )[0]

    assert included["included_refs"] == ["C1", "U1"]
    assert excluded["included_refs"] == []
    assert excluded["omitted_refs"] == ["C1", "U1"]


def test_generate_assembly_variants_disambiguates_colliding_file_tokens():
    comps = [_comp("R1")]

    variants = generate_assembly_variants(
        comps,
        [{"name": "A/B"}, {"name": "A B"}, {"name": "A_B"}],
    )

    assert [variant["token"] for variant in variants] == ["a_b", "a_b_2", "a_b_3"]


def test_generate_assembly_variants_rejects_unknown_or_resolved_empty_include_refs():
    comps = [_comp("R1")]

    with pytest.raises(ValueError, match="unknown active reference.*R99"):
        generate_assembly_variants(comps, [{"name": "typo", "include_refs": ["R99"]}])
    with pytest.raises(ValueError, match="resolve to no active assembly items"):
        generate_assembly_variants(
            comps,
            [{"name": "contradiction", "include_refs": ["R1"], "exclude_refs": ["R1"]}],
        )


def test_export_jlcpcb_writes_variant_bom_and_cpl_from_real_board(tmp_path):
    comps = [_comp("R1"), _comp("R2")]
    board = tmp_path / "real.kicad_pcb"
    _write_real_pcb(board)

    with (
        patch("circuit_weaver.dispatcher.compile_design_ir", return_value=SimpleNamespace(components=comps)),
        patch("circuit_weaver.jlcpcb_export._detect_price_breaks", return_value=[]),
    ):
        result = export_jlcpcb(
            {"project": "board"},
            tmp_path,
            assembly_variants=[{"name": "R1 Only", "include_refs": ["R1"]}],
            pcb_path=board,
        )

    assert result["status"] == "ok"
    assert result["assembly_ready"] is True
    assert result["fabrication_ready"] is False
    assert len(result["assembly_variants"]) == 1
    variant = result["assembly_variants"][0]
    assert variant["name"] == "R1 Only"
    assert variant["component_count"] == 1
    assert (tmp_path / "bom_jlcpcb_r1_only.csv").exists()
    assert (tmp_path / "cpl_jlcpcb_r1_only.csv").exists()
    assert "R1" in (tmp_path / "bom_jlcpcb_r1_only.csv").read_text(encoding="utf-8")
    assert "R2" not in (tmp_path / "bom_jlcpcb_r1_only.csv").read_text(encoding="utf-8")
    delivery = json.loads((tmp_path / "delivery_manifest.json").read_text(encoding="utf-8"))
    artifact_paths = {artifact["path"] for artifact in delivery["artifacts"]}
    assert all(not Path(path).is_absolute() for path in artifact_paths)
    assert "bom_jlcpcb_r1_only.csv" in artifact_paths
    assert "cpl_jlcpcb_r1_only.csv" in artifact_paths


def test_export_jlcpcb_without_physical_board_is_truthful_bom_only(tmp_path):
    component = _comp("U1", value="SENSOR", footprint="Package_QFN:QFN-8", lcsc="C123")
    component.bypass_caps = [
        BypassCap("1", "VDD", "GND", "100nF", "Capacitor_SMD:C_0402")
    ]
    with (
        patch(
            "circuit_weaver.dispatcher.compile_design_ir",
            return_value=SimpleNamespace(components=[component]),
        ),
        patch("circuit_weaver.jlcpcb_export._detect_price_breaks", return_value=[]),
    ):
        result = export_jlcpcb({"project": "board"}, tmp_path)

    assert result["status"] == "bom_only"
    assert result["fabrication_ready"] is False
    assert result["cpl"] == ""
    assert not (tmp_path / "cpl_jlcpcb.csv").exists()
    assert result["assembly_item_count"] == 2
    manifest = json.loads((tmp_path / "assembly_manifest.json").read_text(encoding="utf-8"))
    assert {item["source_kind"] for item in manifest["items"]} == {"component", "bypass"}
    delivery = json.loads((tmp_path / "delivery_manifest.json").read_text(encoding="utf-8"))
    assert delivery["status"] == "bom_only"
    assert delivery["assembly_ready"] is False
    assert delivery["fabrication_ready"] is False
    assert all(not Path(artifact["path"]).is_absolute() for artifact in delivery["artifacts"])
    assert any("real, pad-bearing" in reason for reason in delivery["blocked_reasons"])


def test_export_jlcpcb_rejects_preview_as_cpl_source_but_preserves_bom(tmp_path):
    board = tmp_path / "preview.kicad_pcb"
    board.write_text(
        '''(kicad_pcb (version 20240108) (generator "schematic_engine placement_preview")
  (footprint "Placement_Preview:Missing_R1" (layer "F.Cu") (at 1 2)
    (property "Reference" "R1" (at 0 0 0)))
)''',
        encoding="utf-8",
    )
    with (
        patch(
            "circuit_weaver.dispatcher.compile_design_ir",
            return_value=SimpleNamespace(components=[_comp("R1")]),
        ),
        patch("circuit_weaver.jlcpcb_export._detect_price_breaks", return_value=[]),
    ):
        result = export_jlcpcb({"project": "board"}, tmp_path, pcb_path=board)

    assert result["status"] == "blocked"
    assert (tmp_path / "bom_jlcpcb.csv").exists()
    assert not (tmp_path / "cpl_jlcpcb.csv").exists()
    assert any("Placement preview" in reason for reason in result["blocked_reasons"])


def test_export_jlcpcb_blocks_matching_ref_with_wrong_physical_footprint(tmp_path):
    board = tmp_path / "stale.kicad_pcb"
    _write_real_pcb(board, refs=("U1",))
    intended = _comp("U1", value="MCU", footprint="Package_QFN:QFN-48", lcsc="C123")

    with (
        patch(
            "circuit_weaver.dispatcher.compile_design_ir",
            return_value=SimpleNamespace(components=[intended]),
        ),
        patch("circuit_weaver.jlcpcb_export._detect_price_breaks", return_value=[]),
    ):
        result = export_jlcpcb({"project": "mismatch"}, tmp_path / "delivery", pcb_path=board)

    assert result["status"] == "blocked"
    assert result["assembly_ready"] is False
    assert result["cpl"] == ""
    assert any("footprint identity mismatch" in reason for reason in result["blocked_reasons"])
    assert not (tmp_path / "delivery" / "cpl_jlcpcb.csv").exists()


def test_export_jlcpcb_rejects_unknown_variant_ref_without_ready_header_files(tmp_path):
    with (
        patch(
            "circuit_weaver.dispatcher.compile_design_ir",
            return_value=SimpleNamespace(components=[_comp("R1")]),
        ),
        patch("circuit_weaver.jlcpcb_export._detect_price_breaks", return_value=[]),
    ):
        result = export_jlcpcb(
            {"project": "variant"},
            tmp_path,
            assembly_variants=[{"name": "typo", "include_refs": ["R99"]}],
        )

    assert result["status"] == "error"
    assert "unknown active reference" in result["message"]
    assert not (tmp_path / "bom_jlcpcb_typo.csv").exists()
    assert not (tmp_path / "cpl_jlcpcb_typo.csv").exists()


def test_bom_only_publish_removes_stale_cpl_and_variant_files(tmp_path):
    stale_names = (
        "bom_jlcpcb.csv",
        "cpl_jlcpcb.csv",
        "bom_jlcpcb_old_variant.csv",
        "cpl_jlcpcb_old_variant.csv",
        "README_jlcpcb.txt",
        "delivery_manifest.json",
    )
    for name in stale_names:
        (tmp_path / name).write_text("stale delivery\n", encoding="utf-8")
    unrelated = tmp_path / "board_notes.txt"
    unrelated.write_text("keep me\n", encoding="utf-8")
    project_readme = tmp_path / "README.txt"
    project_readme.write_text("user-owned project readme\n", encoding="utf-8")

    with (
        patch(
            "circuit_weaver.dispatcher.compile_design_ir",
            return_value=SimpleNamespace(components=[_comp("R1")]),
        ),
        patch("circuit_weaver.jlcpcb_export._detect_price_breaks", return_value=[]),
    ):
        result = export_jlcpcb({"project": "board"}, tmp_path)

    assert result["status"] == "bom_only"
    assert "stale delivery" not in (tmp_path / "bom_jlcpcb.csv").read_text(encoding="utf-8")
    assert not (tmp_path / "cpl_jlcpcb.csv").exists()
    assert not (tmp_path / "bom_jlcpcb_old_variant.csv").exists()
    assert not (tmp_path / "cpl_jlcpcb_old_variant.csv").exists()
    assert unrelated.read_text(encoding="utf-8") == "keep me\n"
    assert project_readme.read_text(encoding="utf-8") == "user-owned project readme\n"
    assert "stale delivery" not in (tmp_path / "README_jlcpcb.txt").read_text(encoding="utf-8")


def test_export_jlcpcb_blocks_empty_active_assembly_even_with_physical_board(tmp_path):
    board = tmp_path / "real.kicad_pcb"
    _write_real_pcb(board, refs=("R1",))

    with (
        patch(
            "circuit_weaver.dispatcher.compile_design_ir",
            return_value=SimpleNamespace(components=[]),
        ),
        patch("circuit_weaver.jlcpcb_export._detect_price_breaks", return_value=[]),
    ):
        result = export_jlcpcb({"project": "empty"}, tmp_path, pcb_path=board)

    assert result["status"] == "blocked"
    assert result["assembly_item_count"] == 0
    assert result["assembly_ready"] is False
    assert result["cpl"] == ""
    assert not (tmp_path / "cpl_jlcpcb.csv").exists()
    assert any("no active BOM items" in reason for reason in result["blocked_reasons"])
    assert any("no active placement references" in reason for reason in result["blocked_reasons"])


def test_publish_failure_removes_stale_and_partial_delivery_outputs(tmp_path):
    owned_names = (
        "assembly_manifest.json",
        "delivery_manifest.json",
        "bom_jlcpcb.csv",
        "cpl_jlcpcb.csv",
        "bom_jlcpcb_old.csv",
        "cpl_jlcpcb_old.csv",
        "README_jlcpcb.txt",
    )
    for name in owned_names:
        (tmp_path / name).write_text("stale delivery\n", encoding="utf-8")
    (tmp_path / "assembly_manifest.json").write_text(
        json.dumps({"schema_version": 2, "items": [], "retired_references": []}),
        encoding="utf-8",
    )
    unrelated = tmp_path / "real.kicad_pcb"
    _write_real_pcb(unrelated, refs=("R1",))
    project_readme = tmp_path / "README.txt"
    project_readme.write_text("preserve me\n", encoding="utf-8")

    real_replace = os.replace
    replace_calls = 0

    def fail_mid_publish(source, destination):
        nonlocal replace_calls
        replace_calls += 1
        if replace_calls == 3:
            raise OSError("simulated publish failure")
        return real_replace(source, destination)

    with (
        patch(
            "circuit_weaver.dispatcher.compile_design_ir",
            return_value=SimpleNamespace(components=[_comp("R1")]),
        ),
        patch("circuit_weaver.jlcpcb_export._detect_price_breaks", return_value=[]),
        patch("circuit_weaver.jlcpcb_export.os.replace", side_effect=fail_mid_publish),
    ):
        result = export_jlcpcb({"project": "board"}, tmp_path)

    assert result["status"] == "error"
    assert "simulated publish failure" in result["message"]
    assert result["files"] == []
    assert all(not (tmp_path / name).exists() for name in owned_names)
    assert unrelated.exists()
    assert project_readme.read_text(encoding="utf-8") == "preserve me\n"
    assert not any(path.name.startswith(".cw-jlc-") for path in tmp_path.iterdir())


def test_concurrent_delivery_publications_cannot_mix_generations(tmp_path):
    destination = tmp_path / "delivery"
    destination.mkdir()
    stage_a = tmp_path / "stage_a"
    stage_b = tmp_path / "stage_b"
    stage_a.mkdir()
    stage_b.mkdir()
    artifact_names = (
        "README_jlcpcb.txt",
        "assembly_manifest.json",
        "bom_jlcpcb.csv",
        "delivery_manifest.json",
    )
    for stage, label in ((stage_a, "A"), (stage_b, "B")):
        for name in artifact_names:
            (stage / name).write_text(f"{label}:{name}\n", encoding="utf-8")

    real_replace = os.replace
    first_payload_moved = threading.Event()
    release_first = threading.Event()
    second_payload_moved = threading.Event()
    errors: list[Exception] = []

    def controlled_replace(source, target):
        source_path = Path(source)
        result = real_replace(source, target)
        if source_path.parent == stage_a and source_path.name == "README_jlcpcb.txt":
            first_payload_moved.set()
            release_first.wait(timeout=5)
        elif source_path.parent == stage_b:
            second_payload_moved.set()
        return result

    def publish(stage):
        try:
            _publish_delivery_staging(stage, destination)
        except Exception as exc:  # pragma: no cover - assertion reports the exception
            errors.append(exc)

    with patch("circuit_weaver.jlcpcb_export.os.replace", side_effect=controlled_replace):
        first = threading.Thread(target=publish, args=(stage_a,))
        first.start()
        assert first_payload_moved.wait(timeout=5)
        second = threading.Thread(target=publish, args=(stage_b,))
        second.start()
        time.sleep(0.1)
        assert not second_payload_moved.is_set()
        release_first.set()
        first.join(timeout=5)
        second.join(timeout=5)

    assert not first.is_alive()
    assert not second.is_alive()
    assert errors == []
    assert second_payload_moved.is_set()
    assert {
        (destination / name).read_text(encoding="utf-8").split(":", 1)[0]
        for name in artifact_names
    } == {"B"}
