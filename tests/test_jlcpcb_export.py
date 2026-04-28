"""Tests for JLCPCB export helpers."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from circuit_weaver.component_db import ComponentDef
from circuit_weaver.jlcpcb_export import (
    _detect_price_breaks,
    export_jlcpcb,
    generate_assembly_variants,
    group_bom_rows,
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


def test_write_jlcpcb_cpl_uses_top_bottom_layer_names(tmp_path):
    path = tmp_path / "cpl.csv"
    comps = [_comp("U1"), _comp("U2")]
    placements = {"U1": (1.0, 2.0, 90.0, "top"), "U2": (3.0, 4.0, 180.0, "bottom")}

    write_jlcpcb_cpl(comps, placements, path)

    text = path.read_text(encoding="utf-8")
    assert "U1,1.00,2.00,90.0,top" in text
    assert "U2,3.00,4.00,180.0,bottom" in text


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
    assert variants[0]["included_refs"] == ["R1", "R2"]
    assert len(variants[0]["components"]) == 2


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


def test_generate_assembly_variants_disambiguates_colliding_file_tokens():
    comps = [_comp("R1")]

    variants = generate_assembly_variants(
        comps,
        [{"name": "A/B"}, {"name": "A B"}, {"name": "A_B"}],
    )

    assert [variant["token"] for variant in variants] == ["a_b", "a_b_2", "a_b_3"]


def test_export_jlcpcb_writes_variant_bom_and_cpl(tmp_path):
    comps = [_comp("R1"), _comp("R2")]
    placements = {"R1": (1.0, 2.0, 0.0, "top"), "R2": (3.0, 4.0, 0.0, "top")}

    with (
        patch("circuit_weaver.dispatcher.compile_design_ir", return_value=SimpleNamespace(components=comps)),
        patch("circuit_weaver.jlcpcb_export.generate_pcb_placement", return_value=("board.kicad_pcb", placements)),
        patch("circuit_weaver.jlcpcb_export._detect_price_breaks", return_value=[]),
    ):
        result = export_jlcpcb(
            {"project": "board"},
            tmp_path,
            assembly_variants=[{"name": "R1 Only", "include_refs": ["R1"]}],
        )

    assert result["status"] == "ok"
    assert len(result["assembly_variants"]) == 1
    variant = result["assembly_variants"][0]
    assert variant["name"] == "R1 Only"
    assert variant["component_count"] == 1
    assert (tmp_path / "bom_jlcpcb_r1_only.csv").exists()
    assert (tmp_path / "cpl_jlcpcb_r1_only.csv").exists()
    assert "R1" in (tmp_path / "bom_jlcpcb_r1_only.csv").read_text(encoding="utf-8")
    assert "R2" not in (tmp_path / "bom_jlcpcb_r1_only.csv").read_text(encoding="utf-8")
