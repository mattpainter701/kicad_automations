"""Mouser symbol autoloader — fetch component metadata via Mouser Search API.

Queries Mouser Search API (requires MOUSER_SEARCH_API_KEY) for component metadata
including package type, then maps to KiCad footprints. Creates a ComponentDef stub
for use in the symbol resolution chain as a fallback after DigiKey.

Cache: Results are stored in SymbolCache with source="mouser" for 30-day TTL reuse.

Usage:
    from circuit_weaver.mouser_loader import load_from_mouser
    from circuit_weaver.symbol_cache import SymbolCache

    cache = SymbolCache()
    comp = load_from_mouser("LMR51450DDAR", cache=cache)
    if comp:
        print(f"Found: {comp.description}, footprint: {comp.footprint}")
"""

from __future__ import annotations

import logging
from typing import Any

from .component_db import ComponentDef, PinDef
from .digikey_loader import _infer_ref_prefix, map_digikey_package_to_kicad
from .parts_lookup import _get_credential, _http_post_json
from .symbol_cache import SymbolCache

log = logging.getLogger(__name__)

_MOUSER_SEARCH_URL = "https://api.mouser.com/api/v1/search/partnumber"


def _get_mouser_key() -> str:
    """Return MOUSER_SEARCH_API_KEY from environment or ~/.config/secrets.env.

    Returns:
        API key string, or empty string if not found.
    """
    return _get_credential("MOUSER_SEARCH_API_KEY")


def _search_mouser(mpn: str) -> dict[str, Any] | None:
    """Search Mouser via Search API v1.

    Args:
        mpn: Manufacturer Part Number.

    Returns:
        Normalised dict with mpn, manufacturer, description, package, datasheet_url,
        mouser_pn, or None if API failure or no results.
    """
    key = _get_mouser_key()
    if not key:
        return None

    url = f"{_MOUSER_SEARCH_URL}?apiKey={key}"
    body = {
        "SearchByPartRequest": {
            "mouserPartNumber": mpn,
            "partSearchOptions": "Exact",
        }
    }

    resp = _http_post_json(url, body)
    if not resp:
        return None

    # Extract results
    search_results = resp.get("SearchResults") or {}
    parts = search_results.get("Parts") or []
    if not parts:
        return None

    # Pick the best match: prefer exact MPN match
    best = None
    for part in parts:
        mfr_pn = part.get("ManufacturerPartNumber", "")
        if mfr_pn.upper() == mpn.upper():
            best = part
            break

    if best is None:
        best = parts[0]

    # Extract package from ProductAttributes
    package = ""
    attrs = best.get("ProductAttributes") or []
    for attr in attrs:
        attr_name = attr.get("AttributeName", "").lower()
        if attr_name in ("package / case", "package"):
            package = attr.get("AttributeValue", "")
            break

    # Parse price tiers
    price_tiers = []
    raw_prices = best.get("PriceBreaks") or []
    for tier in raw_prices:
        try:
            # Mouser price is a string like "$0.10"
            price_str = tier.get("Price", "0")
            if isinstance(price_str, str) and price_str.startswith("$"):
                price_str = price_str[1:]
            unit_price = float(price_str)
            price_tiers.append(
                {
                    "min_qty": int(tier.get("Quantity", 1)),
                    "max_qty": 999999,
                    "unit_price": unit_price,
                }
            )
        except (TypeError, ValueError):
            continue

    return {
        "source": "mouser",
        "mpn": best.get("ManufacturerPartNumber", ""),
        "manufacturer": best.get("Manufacturer", ""),
        "description": best.get("Description", ""),
        "package": package,
        "datasheet_url": best.get("DataSheetUrl", ""),
        "mouser_pn": best.get("MouserPartNumber", ""),
        "stock": best.get("QuantityAvailable", 0),
        "price_tiers": price_tiers,
    }


def load_from_mouser(mpn: str, cache: SymbolCache | None = None) -> ComponentDef | None:
    """Query Mouser for an MPN; create a ComponentDef stub with footprint info.

    Tries cache first. On cache miss, queries Mouser Search API (requires
    MOUSER_SEARCH_API_KEY credential). Builds a minimal ComponentDef stub
    with the footprint mapped from Mouser's package data. Caches result
    for 30 days.

    Args:
        mpn: Manufacturer Part Number (e.g., "LMR51450DDAR").
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
        log.debug("Cache hit for Mouser MPN %s", mpn)
        # Build a minimal stub from cached data
        return ComponentDef(
            mpn=mpn,
            ref_prefix=_infer_ref_prefix(cached.get("description", "")),
            value=mpn,
            footprint=cached.get("footprint", ""),
            description=cached.get("description", ""),
            source_manufacturer=cached.get("manufacturer", ""),
            digikey_pn="",
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
    if not _get_mouser_key():
        log.debug("Mouser API key not configured — skipping MPN %s", mpn)
        return None

    # Query Mouser API
    data = _search_mouser(mpn)
    if not data:
        log.debug("Mouser API returned no results for MPN %s", mpn)
        return None

    # Map package to KiCad footprint
    footprint = map_digikey_package_to_kicad(data.get("package", ""))

    # Build stub ComponentDef
    stub = ComponentDef(
        mpn=mpn,
        ref_prefix=_infer_ref_prefix(data.get("description", "")),
        value=mpn,
        footprint=footprint,
        description=data.get("description", ""),
        source_manufacturer=data.get("manufacturer", ""),
        digikey_pn="",
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
            "source": "mouser",
            "footprint": footprint,
            "manufacturer": data.get("manufacturer", ""),
            "description": data.get("description", ""),
            "digikey_pn": "",
            "lcsc": "",
            "mouser_pn": data.get("mouser_pn", ""),
        },
    )

    log.info("Loaded Mouser stub for %s: footprint=%s", mpn, footprint)
    return stub
