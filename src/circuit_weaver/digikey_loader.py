"""DigiKey symbol autoloader — fetch component metadata via DigiKey API.

Queries DigiKey API (OAuth 2.0 client credentials) for component metadata including
package type, then maps to KiCad footprints. Creates a ComponentDef stub suitable
for use in the symbol resolution chain when full EasyEDA symbol data is unavailable.

Cache: Results are stored in SymbolCache with source="digikey" for 30-day TTL reuse.

Usage:
    from circuit_weaver.digikey_loader import load_from_digikey
    from circuit_weaver.symbol_cache import SymbolCache

    cache = SymbolCache()
    comp = load_from_digikey("TPS62A01DRLR", cache=cache)
    if comp:
        print(f"Found: {comp.description}, footprint: {comp.footprint}")
    else:
        print("Not found or DigiKey credentials unavailable")
"""

from __future__ import annotations

import logging

from .component_db import ComponentDef, PinDef
from .parts_lookup import _get_credential, _search_digikey
from .symbol_cache import SymbolCache

log = logging.getLogger(__name__)

# DigiKey package strings → KiCad footprint library paths
_DK_PACKAGE_MAP: dict[str, str] = {
    "SOT-23-3": "Package_TO_SOT_SMD:SOT-23",
    "SOT-23-5": "Package_TO_SOT_SMD:SOT-23-5",
    "SOT-23-6": "Package_TO_SOT_SMD:SOT-23-6",
    "SOT-89-3": "Package_TO_SOT_SMD:SOT-89-3",
    "SOT-223-3": "Package_TO_SOT_SMD:SOT-223-3",
    "SC-70-5": "Package_TO_SOT_SMD:SC-70-5",
    "DIP-8": "Package_DIP:DIP-8_W7.62mm",
    "DIP-14": "Package_DIP:DIP-14_W7.62mm",
    "DIP-16": "Package_DIP:DIP-16_W7.62mm",
    "DIP-28": "Package_DIP:DIP-28_W7.62mm",
    "SOIC-8": "Package_SO:SOIC-8_3.9x4.9mm_P1.27mm",
    "SOIC-16": "Package_SO:SOIC-16_3.9x9.9mm_P1.27mm",
    "SOIC-20": "Package_SO:SOIC-20W_7.5x12.8mm_P1.27mm",
    "TSSOP-8": "Package_SO:TSSOP-8_4.4x3mm_P0.65mm",
    "TSSOP-16": "Package_SO:TSSOP-16_4.4x5mm_P0.65mm",
    "TSSOP-20": "Package_SO:TSSOP-20_4.4x6.5mm_P0.65mm",
    "QFN-16": "Package_DFN_QFN:QFN-16-1EP_3x3mm_P0.5mm_EP1.7x1.7mm",
    "QFN-20": "Package_DFN_QFN:QFN-20-1EP_4x4mm_P0.65mm_EP2.5x2.5mm",
    "QFN-32": "Package_DFN_QFN:QFN-32-1EP_5x5mm_P0.5mm_EP3.1x3.1mm",
    "QFN-48": "Package_DFN_QFN:QFN-48-1EP_7x7mm_P0.5mm_EP5.6x5.6mm",
    "QFP-32": "Package_QFP:LQFP-32_7x7mm_P0.8mm",
    "QFP-48": "Package_QFP:LQFP-48_7x7mm_P0.5mm",
    "QFP-64": "Package_QFP:LQFP-64_10x10mm_P0.5mm",
    "0402": "Resistor_SMD:R_0402_1005Metric",
    "0603": "Resistor_SMD:R_0603_1608Metric",
    "0805": "Resistor_SMD:R_0805_2012Metric",
    "1206": "Resistor_SMD:R_1206_3216Metric",
    "TO-252-2": "Package_TO_SOT_SMD:TO-252-2",
    "TO-263-3": "Package_TO_SOT_SMD:TO-263-2",
    "DPAK": "Package_TO_SOT_SMD:TO-252-2",
    "D2PAK": "Package_TO_SOT_SMD:TO-263-2",
    "BGA-256": "Package_BGA:BGA-256_23x23mm_Layout16x16_P1.27mm",
    "BGA-144": "Package_BGA:BGA-144_13x13mm_Layout12x12_P1.0mm",
}

_PREFIX_KEYWORDS: dict[str, list[str]] = {
    "U": ["regulator", "converter", "controller", "amplifier", "mcu", "processor", "fpga", "ic"],
    "Q": ["transistor", "mosfet", "bjt"],
    "D": ["diode", "schottky", "zener", "tvs"],
    "J": ["connector", "header", "socket"],
    "L": ["inductor", "choke"],
    "C": ["capacitor"],
    "R": ["resistor"],
    "Y": ["crystal", "oscillator"],
}


def map_digikey_package_to_kicad(dk_package: str) -> str:
    """Map a DigiKey package string to a KiCad footprint library path.

    Tries exact match first, then prefix match. Returns empty string if unmapped.

    Args:
        dk_package: DigiKey package name (e.g., "SOT-23-5", "DIP-8", "0402").

    Returns:
        KiCad footprint path (e.g., "Package_TO_SOT_SMD:SOT-23-5") or "".
    """
    if not dk_package:
        return ""

    # Exact match first
    if dk_package in _DK_PACKAGE_MAP:
        return _DK_PACKAGE_MAP[dk_package]

    # Prefix match (e.g., "SOT-23" matches "SOT-23-3" or "SOT-23-5")
    for dk_key, kicad_fp in _DK_PACKAGE_MAP.items():
        if dk_package.upper().startswith(dk_key.upper()):
            return kicad_fp

    return ""


def _infer_ref_prefix(description: str) -> str:
    """Heuristic: infer component reference prefix from description keywords.

    Examples:
        "Linear regulator" → "U"
        "MOSFET N-channel" → "Q"
        "Schottky diode" → "D"

    Args:
        description: Component description string.

    Returns:
        Reference prefix (default "U").
    """
    desc_lower = description.lower() if description else ""

    for prefix, keywords in _PREFIX_KEYWORDS.items():
        for kw in keywords:
            if kw in desc_lower:
                return prefix

    return "U"  # Default: integrated circuit


def load_from_digikey(mpn: str, cache: SymbolCache | None = None) -> ComponentDef | None:
    """Query DigiKey for an MPN; create a ComponentDef stub with footprint info.

    Tries cache first. On cache miss, queries DigiKey API (requires
    DIGIKEY_CLIENT_ID and DIGIKEY_CLIENT_SECRET credentials). Builds a
    minimal ComponentDef stub with the footprint mapped from DigiKey's
    package data. Caches result for 30 days.

    Args:
        mpn: Manufacturer Part Number (e.g., "TPS62A01DRLR").
        cache: Optional SymbolCache instance. If None, results are not cached.

    Returns:
        ComponentDef stub with footprint and metadata, or None if not found
        or credentials unavailable.
    """
    if not cache:
        cache = SymbolCache()

    # Try cache hit
    cached = cache.get(mpn)
    if cached:
        log.debug("Cache hit for DigiKey MPN %s", mpn)
        # Build a minimal stub from cached data
        return ComponentDef(
            mpn=mpn,
            ref_prefix=_infer_ref_prefix(cached.get("description", "")),
            value=mpn,
            footprint=cached.get("footprint", ""),
            description=cached.get("description", ""),
            source_manufacturer=cached.get("manufacturer", ""),
            digikey_pn=cached.get("digikey_pn", ""),
            lcsc_pn=cached.get("lcsc", ""),
            features=[],
            annotations=[],
            pinout_source="stub",
            pins=[PinDef("1", "~", "passive", "L"), PinDef("2", "~", "passive", "R")],
            pin_nets={},
            power_pins={},
            power_reqs=[],
            bypass_caps=[],
            straps=[],
            explicit_no_connects=set(),
        )

    # Check credentials
    if not _get_credential("DIGIKEY_CLIENT_ID") or not _get_credential("DIGIKEY_CLIENT_SECRET"):
        log.debug("DigiKey credentials not configured — skipping MPN %s", mpn)
        return None

    # Query DigiKey API
    data = _search_digikey(mpn)
    if not data:
        log.debug("DigiKey API returned no results for MPN %s", mpn)
        return None

    # Extract package string from Parameters
    package = ""
    for param in data.get("parameters", []):
        if isinstance(param, dict) and param.get("name", "").lower() in ("package / case", "package"):
            package = param.get("value", "")
            break

    footprint = map_digikey_package_to_kicad(package)

    # Build stub ComponentDef
    stub = ComponentDef(
        mpn=mpn,
        ref_prefix=_infer_ref_prefix(data.get("description", "")),
        value=mpn,
        footprint=footprint,
        description=data.get("description", ""),
        source_manufacturer=data.get("manufacturer", ""),
        digikey_pn=data.get("digikey_pn", ""),
        lcsc_pn="",
        features=[],
        annotations=[],
        pinout_source="stub",
        pins=[PinDef("1", "~", "passive", "L"), PinDef("2", "~", "passive", "R")],
        pin_nets={},
        power_pins={},
        power_reqs=[],
        bypass_caps=[],
        straps=[],
        explicit_no_connects=set(),
    )

    # Cache for future use
    cache.put(
        mpn,
        {
            "source": "digikey",
            "footprint": footprint,
            "manufacturer": data.get("manufacturer", ""),
            "description": data.get("description", ""),
            "digikey_pn": data.get("digikey_pn", ""),
            "lcsc": "",
        },
    )

    log.info("Loaded DigiKey stub for %s: footprint=%s", mpn, footprint)
    return stub
