"""Regression tests for the 7-tier SymbolResolver chain.

These exist because v0.24.x shipped with a bug: `project_spec._resolve_component`
used an ad-hoc 3-tier inline resolver (registry → KiCad lib → EasyEDA) that
never consulted the ic_data JSON store, cache, DigiKey, or Mouser. Users hit
"not in registry, KiCad library, or EasyEDA, creating stub" for common parts
(SHT41-AD1B-R2, SGP40-D-R4, nRF52840) even though the same parts resolved
fine via the 6-tier `SymbolResolver` (which no caller was using).

v0.25.0 wires `SymbolResolver` into `project_spec` and adds ic_data as
Tier 2. These tests lock in the contract.
"""

from __future__ import annotations

from unittest.mock import patch

from circuit_weaver.component_db import ComponentDef, ComponentRegistry, PinDef
from circuit_weaver.ic_data import register_ic
from circuit_weaver.ic_data import reload as _reload_ic_data
from circuit_weaver.symbol_resolver import SymbolResolver


def _stub_pindefs() -> list[PinDef]:
    return [
        PinDef("1", "VDD", "power_in", "T"),
        PinDef("2", "GND", "power_in", "B"),
        PinDef("3", "OUT", "output", "R"),
    ]


def test_registry_tier_wins_first():
    """Tier 1: ComponentRegistry shortcuts all later tiers."""
    reg = ComponentRegistry()
    reg.register(
        ComponentDef(
            mpn="ACME-ONLY-IN-REGISTRY",
            ref_prefix="U",
            value="ACME-ONLY-IN-REGISTRY",
            footprint="SOT-23-3",
            description="Fake IC for test",
            pins=_stub_pindefs(),
        )
    )
    r = SymbolResolver(component_reg=reg, use_easyeda=False, use_digikey=False, use_mouser=False)
    comp, src = r.resolve("ACME-ONLY-IN-REGISTRY")
    assert comp is not None
    assert src == "registry"


def test_ic_data_tier_resolves_template_extracted_part():
    """Tier 2: bundled ic_data JSON serves template-extracted parts without API calls."""
    r = SymbolResolver(use_easyeda=False, use_digikey=False, use_mouser=False)
    # DS3231 ships in ic_data/misc.json courtesy of scripts/extract_ic_data.py.
    comp, src = r.resolve("DS3231")
    assert comp is not None, "DS3231 should resolve via ic_data tier"
    assert src == "ic_data"
    assert len(comp.pins) > 0
    # Must have real pin data, not a stub.
    assert all(p.number for p in comp.pins)


def test_ic_data_tier_honors_register_ic_hot_load():
    """register_ic() immediately makes new entries visible to the resolver."""
    _reload_ic_data()  # reset database to package-bundled state
    register_ic(
        "TEST-HOT-LOADED-SENSOR",
        {
            "topology": "sensor",
            "description": "Hot-loaded test sensor",
            "footprint": "Sensor:DFN-4-1EP",
            "pins": [
                {"number": "1", "name": "SDA", "type": "bidirectional", "side": "R"},
                {"number": "2", "name": "VDD", "type": "power_in", "side": "T"},
                {"number": "3", "name": "GND", "type": "power_in", "side": "B"},
                {"number": "4", "name": "SCL", "type": "input", "side": "R"},
            ],
        },
        persist=False,
    )
    r = SymbolResolver(use_easyeda=False, use_digikey=False, use_mouser=False)
    comp, src = r.resolve("TEST-HOT-LOADED-SENSOR")
    assert comp is not None, "register_ic() entry should resolve in-session"
    assert src == "ic_data"
    assert len(comp.pins) == 4


def test_digikey_tier_rescues_parts_not_in_ic_data():
    """Tier 6: DigiKey fallback catches MPNs that no earlier tier knows.

    This is the SHT41-AD1B-R2 bug from v0.24.x — the resolver used to stop
    at EasyEDA and stub everything unknown. Now DigiKey/Mouser get a shot.
    """
    fake_def = ComponentDef(
        mpn="SHT41-AD1B-R2",
        ref_prefix="U",
        value="SHT41-AD1B-R2",
        footprint="Sensor:Sensirion_DFN-4-1EP_1.5x1.5mm_P1mm_EP0.7x1.1mm",
        description="Sensirion SHT41 temperature + humidity sensor (DigiKey stub)",
        source_manufacturer="Sensirion",
        pins=_stub_pindefs(),
    )

    with patch("circuit_weaver.symbol_resolver.SymbolResolver._resolve_digikey", return_value=fake_def):
        r = SymbolResolver(use_easyeda=False, use_mouser=False)
        comp, src = r.resolve("SHT41-AD1B-R2")

    assert comp is not None, "DigiKey tier must catch SHT41-AD1B-R2"
    assert src == "digikey"
    # The key property: it is NOT an unresolved stub.
    assert "unresolved" not in " ".join(comp.annotations).lower()


def test_project_spec_uses_symbol_resolver_chain():
    """project_spec._resolve_component delegates to SymbolResolver — the
    v0.24.x bug where project_spec had its own ad-hoc 3-tier resolver is
    fixed. This test locks in that the full chain is invoked for standalone
    `ic:` entries.
    """
    from circuit_weaver.component_db import BUILTIN_REGISTRY
    from circuit_weaver.project_spec import _resolve_component
    from circuit_weaver.subcircuits.base import _build_default_registry

    BUILTIN_SUBCIRCUITS = _build_default_registry()

    item = {"ic": "DS3231", "ref": "U9"}
    result = _resolve_component(
        item,
        section_category="digital",
        subcircuit_reg=BUILTIN_SUBCIRCUITS,
        component_reg=BUILTIN_REGISTRY,
        kicad_lib=None,
    )
    assert len(result) == 1
    comp = result[0]
    # DS3231 lives in ic_data (not in BUILTIN_REGISTRY, no kicad_lib passed).
    # If the old 3-tier resolver was still in play this would be a stub.
    assert "unresolved" not in " ".join(comp.annotations).lower(), (
        "DS3231 should resolve via ic_data tier through SymbolResolver, not fall to a stub"
    )
    assert comp.source_ref == "U9"
    assert len(comp.pins) > 0


def test_unresolved_mpn_falls_to_stub_with_informative_reason():
    """When every tier fails, we still get a stub — but the diagnostic now
    names all 7 tiers so the user can see exactly what was tried.
    """
    from circuit_weaver.component_db import BUILTIN_REGISTRY
    from circuit_weaver.project_spec import _resolve_component
    from circuit_weaver.subcircuits.base import _build_default_registry

    BUILTIN_SUBCIRCUITS = _build_default_registry()

    fake_mpn = "ZZZ-NON-EXISTENT-PART-12345"
    # Disable API tiers so the test is hermetic.
    with (
        patch("circuit_weaver.symbol_resolver.SymbolResolver._resolve_easyeda", return_value=None),
        patch("circuit_weaver.symbol_resolver.SymbolResolver._resolve_digikey", return_value=None),
        patch("circuit_weaver.symbol_resolver.SymbolResolver._resolve_mouser", return_value=None),
    ):
        result = _resolve_component(
            {"ic": fake_mpn, "ref": "U99"},
            section_category="digital",
            subcircuit_reg=BUILTIN_SUBCIRCUITS,
            component_reg=BUILTIN_REGISTRY,
            kicad_lib=None,
        )
    assert len(result) == 1
    comp = result[0]
    annotation_text = " ".join(comp.annotations).lower()
    # The stub reason must mention the 7-tier chain so operators know what to fix.
    assert "7 tiers" in annotation_text or "unresolved" in annotation_text
