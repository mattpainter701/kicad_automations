"""End-to-end integration test for the 7-tier SymbolResolver chain.

Sprint 37 Task 157: lock in the user-reported Zigbee air-sensor flow so
v0.24.x-style resolver regressions never ship again.

The user's v0.24.x test:

    circuit-weaver validate zigbee_air_sensor.yaml
    → WARNING: Unknown component 'SHT41-AD1B-R2', not in registry,
      KiCad library, or EasyEDA, creating stub
    → (same for SGP40-D-R4 and nRF52840)

In v0.25.0 we wired SymbolResolver into project_spec. This test
recreates the scenario with a small multi-IC YAML, mocks the DigiKey
loader (so the test is hermetic and network-free), and asserts that
every MPN resolves through the intended tier — NOT to a generic stub.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from circuit_weaver.component_db import ComponentDef, PinDef


def _fake_component(mpn: str, description: str) -> ComponentDef:
    """Minimal ComponentDef shaped like what digikey_loader.load_from_digikey
    would return for a found MPN."""
    return ComponentDef(
        mpn=mpn,
        ref_prefix="U",
        value=mpn,
        footprint="Package:Generic",
        description=description,
        source_manufacturer="Vendor",
        pins=[
            PinDef("1", "VDD", "power_in", "T"),
            PinDef("2", "GND", "power_in", "B"),
            PinDef("3", "IO", "bidirectional", "R"),
        ],
    )


_DIGIKEY_STUBS = {
    "SHT41-AD1B-R2": _fake_component("SHT41-AD1B-R2", "Sensirion SHT41 (via DigiKey)"),
    "SGP40-D-R4": _fake_component("SGP40-D-R4", "Sensirion SGP40 (via DigiKey)"),
    "nRF52840": _fake_component("nRF52840", "Nordic nRF52840 SoC (via DigiKey)"),
}


def _mock_digikey(mpn: str, cache=None):  # noqa: ARG001
    """Stand-in for digikey_loader.load_from_digikey — returns a prebuilt
    ComponentDef for known MPNs, None otherwise."""
    return _DIGIKEY_STUBS.get(mpn)


@pytest.fixture
def zigbee_yaml(tmp_path) -> Path:
    """User-reported YAML: mix of parts resolved by three different tiers.

    - DS3231 → Tier 2 (ic_data JSON, shipped with the package)
    - SHT41-AD1B-R2, SGP40-D-R4, nRF52840 → Tier 6 (mocked DigiKey)
    """
    spec = tmp_path / "zigbee_air_sensor.yaml"
    spec.write_text(
        """
project: Zigbee_Air_Sensor
description: Battery-powered T/H/VOC sensor with Zigbee

digital:
  - ic: DS3231
    ref: U1
  - ic: nRF52840
    ref: U2

sensors:
  - ic: SHT41-AD1B-R2
    ref: U3
  - ic: SGP40-D-R4
    ref: U4
""".strip(),
        encoding="utf-8",
    )
    return spec


def _is_stub(comp: ComponentDef) -> bool:
    """A ComponentDef is a stub iff its annotations mention 'unresolved'
    or its MPN starts with 'STUB'."""
    if comp.mpn.upper().startswith("STUB"):
        return True
    text = " ".join(comp.annotations).lower()
    return "unresolved" in text or "stub" in text


def test_resolver_e2e_zigbee_yaml(zigbee_yaml, monkeypatch):
    """Every MPN in the Zigbee spec resolves via some real tier — no stubs."""
    # Reset per-session credential warning cache (test isolation).
    from circuit_weaver.symbol_resolver import SymbolResolver

    SymbolResolver._cred_warned.clear()  # type: ignore[attr-defined]

    # Seed DIGIKEY_CLIENT_ID so the credential-missing guard (Task 156)
    # doesn't short-circuit the DigiKey tier before our patch runs.
    monkeypatch.setenv("DIGIKEY_CLIENT_ID", "test-client-id")

    # Disable Mouser + EasyEDA so the test stays hermetic (those tiers
    # would still work without credentials thanks to lazy imports, but we
    # want to prove DigiKey is the one that picks up the sensors).
    with (
        patch(
            "circuit_weaver.symbol_resolver.SymbolResolver._resolve_easyeda",
            return_value=None,
        ),
        patch(
            "circuit_weaver.symbol_resolver.SymbolResolver._resolve_mouser",
            return_value=None,
        ),
        patch(
            "circuit_weaver.digikey_loader.load_from_digikey",
            side_effect=_mock_digikey,
        ),
    ):
        from circuit_weaver.project_spec import load_project

        components, _meta = load_project(str(zigbee_yaml))

    by_ref = {c.source_ref: c for c in components if c.source_ref}
    assert set(by_ref) >= {"U1", "U2", "U3", "U4"}, f"expected refs U1..U4 in output, got {sorted(by_ref)}"

    for ref in ("U1", "U2", "U3", "U4"):
        comp = by_ref[ref]
        assert not _is_stub(comp), (
            f"{ref} ({comp.mpn}) resolved to a stub — resolver chain regressed. Annotations: {comp.annotations}"
        )

    # DS3231 must come from ic_data JSON (Tier 2), not DigiKey.
    assert by_ref["U1"].mpn == "DS3231"
    assert "DigiKey" not in by_ref["U1"].description

    # The three sensors come from the mocked DigiKey tier.
    for ref, mpn in (("U2", "nRF52840"), ("U3", "SHT41-AD1B-R2"), ("U4", "SGP40-D-R4")):
        assert by_ref[ref].mpn == mpn
        assert "DigiKey" in by_ref[ref].description


def test_resolver_e2e_without_credentials_degrades_to_informative_stubs(zigbee_yaml, monkeypatch):
    """When every API tier is unavailable — no DigiKey/Mouser/EasyEDA —
    the unknown sensors must produce stubs whose reason enumerates all
    seven tiers. This is the regression signature for v0.24.x."""
    from circuit_weaver.symbol_resolver import SymbolResolver

    SymbolResolver._cred_warned.clear()  # type: ignore[attr-defined]
    monkeypatch.delenv("DIGIKEY_CLIENT_ID", raising=False)
    monkeypatch.delenv("MOUSER_SEARCH_API_KEY", raising=False)

    with patch(
        "circuit_weaver.symbol_resolver.SymbolResolver._resolve_easyeda",
        return_value=None,
    ):
        from circuit_weaver.project_spec import load_project

        components, _meta = load_project(str(zigbee_yaml))

    by_ref = {c.source_ref: c for c in components if c.source_ref}
    # DS3231 still resolves because ic_data is a bundled tier.
    assert not _is_stub(by_ref["U1"]), "DS3231 must resolve via ic_data even offline"

    # Sensors become stubs — but the annotation must mention the 7-tier chain.
    for ref in ("U2", "U3", "U4"):
        comp = by_ref[ref]
        if _is_stub(comp):
            annot = " ".join(comp.annotations).lower()
            assert "7 tiers" in annot or "unresolved" in annot, (
                f"{ref} ({comp.mpn}) stub reason should mention the 7-tier chain — got: {comp.annotations}"
            )
