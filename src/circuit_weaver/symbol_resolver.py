"""Unified symbol resolution chain — multi-tier fallback for component lookup.

Implements a 6-tier resolution chain:
1. Custom ComponentRegistry
2. KiCad library
3. SymbolCache (30-day TTL)
4. EasyEDA (full symbol with pins via LCSC)
5. DigiKey (stub with footprint data)
6. Mouser (stub with footprint data)

Falls back to unresolved stub if all tiers fail.

Usage:
    from circuit_weaver.symbol_resolver import SymbolResolver
    from circuit_weaver.symbol_cache import SymbolCache

    resolver = SymbolResolver(cache=SymbolCache())
    comp, source = resolver.resolve("TPS62A01DRLR")
    print(f"Found via {source}: {comp.description}")
    # Output: Found via digikey: Boost converter ...

Loaders are imported lazily to avoid startup failures if API keys are absent.
"""

from __future__ import annotations

import logging
from typing import Any

from .component_db import ComponentDef, ComponentRegistry
from .easyeda_api import fetch_easyeda_component
from .easyeda_parser import easyeda_to_component_def
from .kicad_lib import KiCadLibrary
from .parts_lookup import _search_lcsc
from .symbol_cache import SymbolCache

log = logging.getLogger(__name__)


class SymbolResolver:
    """Unified symbol resolution chain with 6-tier fallback strategy.

    Attributes:
        _reg: Custom ComponentRegistry (Tier 1)
        _kicad: KiCad library (Tier 2)
        _cache: SymbolCache (Tier 3)
        _use_dk: Enable DigiKey loader (Tier 5)
        _use_mouser: Enable Mouser loader (Tier 6)
        _use_easyeda: Enable EasyEDA loader (Tier 4)
    """

    def __init__(
        self,
        component_reg: ComponentRegistry | None = None,
        kicad_lib: KiCadLibrary | None = None,
        cache: SymbolCache | None = None,
        use_digikey: bool = True,
        use_mouser: bool = True,
        use_easyeda: bool = True,
    ) -> None:
        """Initialize resolver with optional registries and cache.

        Args:
            component_reg: Custom ComponentRegistry (Tier 1).
            kicad_lib: KiCad library (Tier 2).
            cache: SymbolCache instance (Tier 3). Defaults to new SymbolCache().
            use_digikey: Enable DigiKey loader (Tier 5).
            use_mouser: Enable Mouser loader (Tier 6).
            use_easyeda: Enable EasyEDA loader (Tier 4).
        """
        self._reg = component_reg
        self._kicad = kicad_lib
        self._cache = cache or SymbolCache()
        self._use_dk = use_digikey
        self._use_mouser = use_mouser
        self._use_easyeda = use_easyeda

    def resolve(
        self,
        mpn: str,
        *,
        item: dict[str, Any] | None = None,
        category: str = "digital",
    ) -> tuple[ComponentDef | None, str]:
        """Resolve an MPN through the full 6-tier chain.

        Returns (ComponentDef | None, source_str) where source_str is one of:
        - "registry" (Tier 1)
        - "kicad" (Tier 2)
        - "cache" (Tier 3: rebuilt from cached metadata)
        - "easyeda" (Tier 4: full symbol via LCSC)
        - "digikey" (Tier 5: stub with footprint)
        - "mouser" (Tier 6: stub with footprint)
        - "unresolved" (all tiers exhausted)

        Args:
            mpn: Manufacturer Part Number to resolve.
            item: Optional dict from YAML spec (unused for now).
            category: Component category for KiCad lib fallback (e.g., "digital").

        Returns:
            Tuple of (ComponentDef or None, source string).
        """
        # Tier 1: Custom registry
        if self._reg:
            comp = self._reg.get(mpn)
            if comp:
                log.debug("Resolved %s via registry", mpn)
                return comp, "registry"

        # Tier 2: KiCad library
        if self._kicad:
            comp = self._kicad.get_component(mpn, category)
            if comp:
                log.debug("Resolved %s via kicad lib", mpn)
                return comp, "kicad"

        # Tier 3: SymbolCache (rebuild from cached index entry)
        cached = self._cache.get(mpn)
        if cached:
            # Rebuild ComponentDef from cached metadata
            comp = self._rebuild_from_cache(mpn, cached)
            log.debug("Resolved %s via cache (source=%s)", mpn, cached.get("source", "unknown"))
            return comp, "cache"

        # Tier 4: EasyEDA (full symbol via LCSC)
        if self._use_easyeda:
            comp = self._resolve_easyeda(mpn)
            if comp:
                log.debug("Resolved %s via easyeda", mpn)
                return comp, "easyeda"

        # Tier 5: DigiKey (stub with footprint)
        if self._use_dk:
            comp = self._resolve_digikey(mpn)
            if comp:
                log.debug("Resolved %s via digikey", mpn)
                return comp, "digikey"

        # Tier 6: Mouser (stub with footprint)
        if self._use_mouser:
            comp = self._resolve_mouser(mpn)
            if comp:
                log.debug("Resolved %s via mouser", mpn)
                return comp, "mouser"

        # All tiers failed
        log.warning("Failed to resolve MPN %s through any tier", mpn)
        return None, "unresolved"

    def resolve_batch(
        self,
        items: list[dict[str, Any]],
        category: str = "digital",
    ) -> list[tuple[str, ComponentDef | None, str]]:
        """Resolve a batch of {mpn/ic: str, ...} dicts.

        Args:
            items: List of component dicts from YAML spec.
            category: Component category for KiCad lib fallback.

        Returns:
            List of (mpn, ComponentDef | None, source) tuples.
        """
        results = []
        for item in items:
            mpn = item.get("ic") or item.get("mpn", "")
            if not mpn:
                continue
            comp, source = self.resolve(mpn, item=item, category=category)
            results.append((mpn, comp, source))
        return results

    def _rebuild_from_cache(self, mpn: str, cached: dict[str, Any]) -> ComponentDef:
        """Rebuild a minimal ComponentDef from cached index metadata.

        Args:
            mpn: Manufacturer Part Number.
            cached: Dict from SymbolCache.get() with source, footprint, etc.

        Returns:
            Minimal ComponentDef with cached fields populated.
        """
        from .component_db import ComponentDef, PinDef

        return ComponentDef(
            mpn=mpn,
            ref_prefix="U",
            value=mpn,
            footprint=cached.get("footprint", ""),
            description=cached.get("description", ""),
            source_manufacturer=cached.get("manufacturer", ""),
            digikey_pn=cached.get("digikey_pn", ""),
            lcsc_pn=cached.get("lcsc", ""),
            features=[],
            annotations=[f"CACHED: from {cached.get('source', 'unknown')} via symbol cache"],
            pins=[PinDef("1", "~", "passive", "L"), PinDef("2", "~", "passive", "R")],
            pin_nets={},
            power_pins={},
            power_reqs=[],
            bypass_caps=[],
            straps=[],
            explicit_no_connects=set(),
        )

    def _resolve_easyeda(self, mpn: str) -> ComponentDef | None:
        """Tier 4: Try LCSC-backed EasyEDA full symbol.

        Args:
            mpn: Manufacturer Part Number.

        Returns:
            Full ComponentDef with pins from EasyEDA, or None if LCSC lookup fails.
        """
        # Search LCSC for the MPN
        lcsc_data = _search_lcsc(mpn)
        if not lcsc_data:
            return None

        lcsc_code = lcsc_data.get("lcsc", "")
        if not lcsc_code:
            return None

        # Fetch EasyEDA symbol
        try:
            easyeda_data = fetch_easyeda_component(lcsc_code)
            if easyeda_data:
                comp = easyeda_to_component_def(easyeda_data)
                if comp:
                    # Enrich with LCSC and datasheet info
                    comp.lcsc_pn = lcsc_code
                    if lcsc_data.get("datasheet_url"):
                        comp.annotations.append(f"Datasheet: {lcsc_data['datasheet_url']}")
                    self._cache.put(
                        mpn,
                        {
                            "source": "easyeda",
                            "footprint": comp.footprint,
                            "lcsc": lcsc_code,
                            "manufacturer": lcsc_data.get("manufacturer", ""),
                            "description": comp.description,
                            "digikey_pn": "",
                        },
                    )
                    return comp
        except Exception as exc:
            log.debug("EasyEDA fetch failed for LCSC %s: %s", lcsc_code, exc)

        return None

    def _resolve_digikey(self, mpn: str) -> ComponentDef | None:
        """Tier 5: Try DigiKey loader (lazy import).

        Args:
            mpn: Manufacturer Part Number.

        Returns:
            ComponentDef stub from DigiKey, or None if unavailable.
        """
        try:
            from .digikey_loader import load_from_digikey

            comp = load_from_digikey(mpn, cache=self._cache)
            if not comp:
                log.debug("DigiKey: MPN not found or API unavailable: %s", mpn)
            return comp
        except ImportError:
            log.debug("DigiKey loader module not available (missing dependencies?)")
            return None
        except Exception as exc:
            log.debug("DigiKey loader error for %s: %s", mpn, exc)
            return None

    def _resolve_mouser(self, mpn: str) -> ComponentDef | None:
        """Tier 6: Try Mouser loader (lazy import).

        Args:
            mpn: Manufacturer Part Number.

        Returns:
            ComponentDef stub from Mouser, or None if unavailable.
        """
        try:
            from .mouser_loader import load_from_mouser

            comp = load_from_mouser(mpn, cache=self._cache)
            if not comp:
                log.debug("Mouser: MPN not found or API unavailable: %s", mpn)
            return comp
        except ImportError:
            log.debug("Mouser loader module not available (missing dependencies?)")
            return None
        except Exception as exc:
            log.debug("Mouser loader error for %s: %s", mpn, exc)
            return None
