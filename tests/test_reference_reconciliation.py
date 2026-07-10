"""Schematic and assembly outputs must agree on support-part identities."""

import re
from pathlib import Path

from circuit_weaver.assembly_manifest import build_assembly_manifest
from circuit_weaver.component_db import BypassCap, ComponentDef, PinDef
from circuit_weaver.generator import generate_from_components


def _owner(ref: str, section: str, category: str, rail: str, cap_value: str) -> ComponentDef:
    return ComponentDef(
        mpn=ref,
        ref_prefix="U",
        source_ref=ref,
        value=ref,
        footprint="Package_DFN_QFN:QFN-16-1EP_3x3mm_P0.5mm_EP1.7x1.7mm",
        category=category,
        pins=[PinDef("1", "VDD", "power_in", "L")],
        power_pins={"1": rail},
        bypass_caps=[
            BypassCap("1", rail, "GND", cap_value, "Capacitor_SMD:C_0402_1005Metric")
        ],
        functional_section=section,
    )


def _schematic_reference_values(paths: list[str]) -> dict[str, str]:
    result: dict[str, str] = {}
    pattern = re.compile(
        r'\(property "Reference" "([A-Za-z]+\d+)".*?'
        r'\(property "Value" "([^"]*)"',
        re.DOTALL,
    )
    for raw_path in paths:
        path = Path(raw_path)
        if path.suffix != ".kicad_sch":
            continue
        for reference, value in pattern.findall(path.read_text(encoding="utf-8")):
            result[reference] = value
    return result


def test_sheet_reordering_does_not_swap_generated_support_refs(tmp_path: Path) -> None:
    # The input order intentionally opposes the allocator's canonical power ->
    # digital sheet order. This reproduced BOM C1/C3 ownership swaps.
    components = [
        _owner("U2", "digital", "digital", "VDD_DIG", "22nF"),
        _owner("U1", "power", "power", "VDD_PWR", "11nF"),
    ]
    manifest = build_assembly_manifest(components)
    expected = {
        item.reference: item.value
        for item in manifest.items
        if item.source_kind in {"bypass", "strap"}
    }

    files = generate_from_components(
        components,
        str(tmp_path),
        project_name="Reference_Reconciliation",
        validate=False,
        readiness_gate=False,
        hierarchical=True,
    )
    actual = _schematic_reference_values(files)

    assert {reference: actual[reference] for reference in expected} == expected
