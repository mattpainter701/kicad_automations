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
from circuit_weaver.symbol_cache import SymbolCache
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


def test_kicad_tier_passes_category_by_keyword():
    """The KiCad API's second positional argument is ``lib_name``.

    Passing the resolver category positionally used to make a digital part
    search for a library named ``digital`` instead of searching the installed
    KiCad libraries.
    """

    expected = ComponentDef(
        mpn="TEST-KICAD-PART",
        ref_prefix="U",
        value="TEST-KICAD-PART",
        footprint="Package:Test",
        description="Resolved from KiCad",
        pins=_stub_pindefs(),
    )

    class FakeKiCadLibrary:
        def __init__(self):
            self.args = None

        def get_component(self, symbol_name, lib_name=None, category="digital"):
            self.args = (symbol_name, lib_name, category)
            return expected

    kicad = FakeKiCadLibrary()
    resolver = SymbolResolver(
        kicad_lib=kicad,
        use_easyeda=False,
        use_digikey=False,
        use_mouser=False,
        use_ic_data=False,
    )
    comp, source = resolver.resolve("TEST-KICAD-PART", category="sensor")

    assert comp is expected
    assert source == "kicad"
    assert kicad.args == ("TEST-KICAD-PART", None, "sensor")


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


def test_digikey_tier_rescues_parts_not_in_ic_data(tmp_path):
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
        r = SymbolResolver(use_easyeda=False, use_mouser=False, cache=SymbolCache(tmp_path / "symbol-cache"))
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


def test_unresolved_mpn_is_cached_within_process():
    """Sprint 41 Task 175: when an MPN fails through every tier, the
    negative result is cached in ``SymbolResolver._unresolved_cache`` so
    a second lookup within the same process returns immediately without
    re-hitting the DigiKey / Mouser loaders.

    A design with N identical unresolvable parts (the toy_phone
    TS-1187A-B-A-B button matrix case) therefore triggers 1 API round
    trip, not N. Transient flaps stay unresolved until the caller
    explicitly calls :meth:`SymbolResolver.clear_unresolved_cache`.
    """
    SymbolResolver.clear_unresolved_cache()

    digikey_calls = {"n": 0}

    def _counting_digikey(self, mpn):  # matches the bound-method signature
        digikey_calls["n"] += 1
        return None  # loader unable to resolve

    with patch.object(SymbolResolver, "_resolve_digikey", _counting_digikey):
        r = SymbolResolver(use_easyeda=False, use_mouser=False, use_ic_data=False)
        first = r.resolve("TS-1187A-B-A-B")
        second = r.resolve("TS-1187A-B-A-B")
        third = r.resolve("TS-1187A-B-A-B")

    assert first == (None, "unresolved")
    assert second == (None, "unresolved")
    assert third == (None, "unresolved")
    assert digikey_calls["n"] == 1, (
        f"first lookup should hit DigiKey once; repeat lookups should be served from the "
        f"negative cache without re-invoking the loader. Observed {digikey_calls['n']} calls."
    )

    # clear_unresolved_cache() re-enables retries.
    SymbolResolver.clear_unresolved_cache()
    with patch.object(SymbolResolver, "_resolve_digikey", _counting_digikey):
        r.resolve("TS-1187A-B-A-B")
    assert digikey_calls["n"] == 2, "clear_unresolved_cache() should allow the next lookup to hit the loader again"


def test_unresolved_cache_does_not_shadow_successful_resolutions():
    """Negative-cache hits must never mask an MPN that was previously
    resolved — the cache only stores exhausted-every-tier failures.
    """
    SymbolResolver.clear_unresolved_cache()

    r = SymbolResolver(use_easyeda=False, use_digikey=False, use_mouser=False)
    # DS3231 is in bundled ic_data.
    comp, src = r.resolve("DS3231")
    assert comp is not None
    assert src == "ic_data"
    assert "DS3231" not in SymbolResolver._unresolved_cache, (
        "successful resolutions must not poison the negative cache — that would block a cold-run "
        "retry after a transient cache miss"
    )


def test_digikey_tier_logs_missing_credential_once(caplog):
    """Sprint 37 Task 156: when DIGIKEY_CLIENT_ID is absent the DigiKey
    tier must log ONE informative INFO line per session, then silently
    skip on subsequent MPNs in the same run.
    """
    # Reset the per-class warn cache so the test sees the first-call path.
    from circuit_weaver.symbol_resolver import SymbolResolver

    SymbolResolver._cred_warned.clear()  # type: ignore[attr-defined]

    r = SymbolResolver(use_easyeda=False, use_mouser=False, use_ic_data=False)
    with (
        patch("circuit_weaver.symbol_resolver._get_credential", return_value=""),
        caplog.at_level("INFO", logger="circuit_weaver.symbol_resolver"),
    ):
        r.resolve("NONEXISTENT-1")
        r.resolve("NONEXISTENT-2")
        r.resolve("NONEXISTENT-3")

    skip_lines = [rec for rec in caplog.records if "DigiKey tier skipped" in rec.getMessage()]
    assert len(skip_lines) == 1, f"expected exactly one 'DigiKey tier skipped' INFO log, got {len(skip_lines)}"
    assert "DIGIKEY_CLIENT_ID" in skip_lines[0].getMessage()
    assert "DIGIKEY_CLIENT_SECRET" in skip_lines[0].getMessage()
    assert "circuit-weaver doctor" in skip_lines[0].getMessage()


def test_digikey_tier_honors_shared_credential_loader(tmp_path):
    """Resolver skip checks must honor the same credential loader as DigiKey."""
    fake_def = ComponentDef(
        mpn="DIGIKEY-SECRETS-ONLY",
        ref_prefix="U",
        value="DIGIKEY-SECRETS-ONLY",
        footprint="Package:Generic",
        description="Loaded via DigiKey credentials from shared loader",
        source_manufacturer="ACME",
        pins=_stub_pindefs(),
    )

    def _cred(name: str) -> str:
        return "configured" if name in ("DIGIKEY_CLIENT_ID", "DIGIKEY_CLIENT_SECRET") else ""

    with (
        patch("circuit_weaver.symbol_resolver._get_credential", side_effect=_cred),
        patch("circuit_weaver.digikey_loader.load_from_digikey", return_value=fake_def),
    ):
        r = SymbolResolver(
            use_easyeda=False,
            use_mouser=False,
            use_ic_data=False,
            cache=SymbolCache(tmp_path / "symbol-cache"),
        )
        comp, src = r.resolve("DIGIKEY-SECRETS-ONLY")

    assert comp is not None
    assert src == "digikey"


def test_mouser_tier_honors_shared_credential_loader(tmp_path):
    fake_def = ComponentDef(
        mpn="MOUSER-SECRETS-ONLY",
        ref_prefix="U",
        value="MOUSER-SECRETS-ONLY",
        footprint="Package:Generic",
        description="Loaded via Mouser credentials from shared loader",
        source_manufacturer="ACME",
        pins=_stub_pindefs(),
    )

    def _cred(name: str) -> str:
        return "configured" if name == "MOUSER_SEARCH_API_KEY" else ""

    with (
        patch("circuit_weaver.symbol_resolver._get_credential", side_effect=_cred),
        patch("circuit_weaver.mouser_loader.load_from_mouser", return_value=fake_def),
    ):
        r = SymbolResolver(
            use_easyeda=False,
            use_digikey=False,
            use_ic_data=False,
            cache=SymbolCache(tmp_path / "symbol-cache"),
        )
        comp, src = r.resolve("MOUSER-SECRETS-ONLY")

    assert comp is not None
    assert src == "mouser"


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


# ---------------------------------------------------------------------------
# Sprint 40 Task 169: cache rebuild must not silently emit 2-pin stubs.
# ---------------------------------------------------------------------------


def test_cache_hit_without_pins_marks_component_as_stub(tmp_path):
    """Cache entries written by metadata-only loaders (DigiKey/Mouser/legacy
    EasyEDA) have no pin topology. The resolver MUST flag the resulting
    ComponentDef as ``pinout_source="stub"`` so the validator's pinout-source
    check fails closed instead of letting a multi-pin IC fly through as a
    2-pin passive.
    """
    cache = SymbolCache(tmp_path / "symbol-cache")
    cache.put(
        "BME688",
        {
            "source": "digikey",
            "footprint": "Package_LGA:LGA-8_3.0x3.0mm_P0.8mm",
            "manufacturer": "Bosch Sensortec",
            "description": "Gas + environmental sensor",
            "digikey_pn": "828-1063-1-ND",
        },
    )

    r = SymbolResolver(
        use_easyeda=False,
        use_digikey=False,
        use_mouser=False,
        use_ic_data=False,
        cache=cache,
    )
    comp, src = r.resolve("BME688")
    assert src == "cache"
    assert comp is not None
    assert comp.pinout_source == "stub", (
        "cache-rebuilt component without pins must be marked stub so the validator's pinout-source gate can block it"
    )
    assert comp.footprint == "Package_LGA:LGA-8_3.0x3.0mm_P0.8mm"


def test_cache_hit_with_full_pin_topology_is_trusted(tmp_path):
    """When the cache payload carries pins + power_pins + bypass_caps (e.g.
    written via ``component_def_to_cache_payload``), a rebuilt component
    MUST be treated as trusted (``pinout_source="explicit"``) and retain
    full topology across sessions.
    """
    from circuit_weaver.symbol_cache import component_def_to_cache_payload

    original = ComponentDef(
        mpn="FAKE-SENSOR-I2C",
        ref_prefix="U",
        value="FAKE-SENSOR-I2C",
        footprint="Package_LGA:LGA-8_3.0x3.0mm_P0.8mm",
        description="Fake cached sensor",
        category="sensor",
        source_manufacturer="ACME",
        pins=[
            PinDef("1", "VDD", "power_in", "T"),
            PinDef("2", "GND", "power_in", "B"),
            PinDef("3", "SDA", "bidirectional", "L"),
            PinDef("4", "SCL", "input", "L"),
            PinDef("5", "CSB", "input", "R"),
            PinDef("6", "SDO", "output", "R"),
            PinDef("7", "NC", "passive", "R"),
            PinDef("8", "VDDIO", "power_in", "T"),
        ],
        power_pins={"1": "VDD_3P3", "8": "VDD_3P3", "2": "GND"},
    )

    cache = SymbolCache(tmp_path / "symbol-cache")
    cache.put(
        "FAKE-SENSOR-I2C",
        component_def_to_cache_payload(original, source="easyeda", lcsc="C000001", manufacturer="ACME"),
    )

    r = SymbolResolver(
        use_easyeda=False,
        use_digikey=False,
        use_mouser=False,
        use_ic_data=False,
        cache=cache,
    )
    comp, src = r.resolve("FAKE-SENSOR-I2C")
    assert src == "cache"
    assert comp is not None
    assert comp.pinout_source == "explicit"
    assert len(comp.pins) == 8
    assert comp.power_pins == {"1": "VDD_3P3", "8": "VDD_3P3", "2": "GND"}
    pin_names = {p.name for p in comp.pins}
    assert {"VDD", "GND", "SDA", "SCL", "VDDIO"}.issubset(pin_names)


def test_cache_stub_fails_pinout_source_validator(tmp_path):
    """End-to-end: a cache-rebuilt stub component triggers the existing
    ``pinout-source`` validator check, producing an ``unverified-pinout``
    error that blocks generation. This is the contract the v0.27.0 fix
    relies on — the validator's gate already exists, but the cache path
    wasn't setting pinout_source correctly.
    """
    from circuit_weaver.validator import run_validation_checks

    cache = SymbolCache(tmp_path / "symbol-cache")
    cache.put(
        "MULTI-PIN-IC",
        {
            "source": "digikey",
            "footprint": "Package_QFP:LQFP-48_7x7mm_P0.5mm",
            "manufacturer": "ACME",
            "description": "Some 48-pin MCU",
        },
    )
    r = SymbolResolver(
        use_easyeda=False,
        use_digikey=False,
        use_mouser=False,
        use_ic_data=False,
        cache=cache,
    )
    comp, _ = r.resolve("MULTI-PIN-IC")
    assert comp is not None
    comp.source_ref = "U5"

    results = run_validation_checks([comp])
    pinout_check = next(r for r in results if r.code == "pinout-source")
    assert pinout_check.status == "FAIL", (
        "pinout-source validator must reject a stub-flagged cache rebuild so "
        "multi-pin ICs can't be emitted as 2-pin passives"
    )
    assert any("unverified-pinout" in (i.code or "") for i in pinout_check.issues)
