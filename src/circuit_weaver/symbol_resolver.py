"""Unified symbol resolution chain — multi-tier fallback for component lookup.

Implements a 7-tier resolution chain:
1. Custom ComponentRegistry
2. ic_data JSON store (user-curated + template-extracted; hot-loadable via register_ic)
3. KiCad library
4. SymbolCache (30-day TTL)
5. EasyEDA (full symbol with pins via LCSC)
6. DigiKey (stub with footprint data)
7. Mouser (stub with footprint data)

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
from .parts_lookup import _get_credential, _search_lcsc
from .symbol_cache import SymbolCache

log = logging.getLogger(__name__)


class SymbolResolver:
    """Unified symbol resolution chain with 7-tier fallback strategy.

    Attributes:
        _reg: Custom ComponentRegistry (Tier 1)
        _use_ic_data: Enable ic_data JSON store lookup (Tier 2)
        _kicad: KiCad library (Tier 3)
        _cache: SymbolCache (Tier 4)
        _use_easyeda: Enable EasyEDA loader (Tier 5)
        _use_dk: Enable DigiKey loader (Tier 6)
        _use_mouser: Enable Mouser loader (Tier 7)
    """

    def __init__(
        self,
        component_reg: ComponentRegistry | None = None,
        kicad_lib: KiCadLibrary | None = None,
        cache: SymbolCache | None = None,
        use_digikey: bool = True,
        use_mouser: bool = True,
        use_easyeda: bool = True,
        use_ic_data: bool = True,
    ) -> None:
        """Initialize resolver with optional registries and cache.

        Args:
            component_reg: Custom ComponentRegistry (Tier 1).
            kicad_lib: KiCad library (Tier 3).
            cache: SymbolCache instance (Tier 4). Defaults to new SymbolCache().
            use_easyeda: Enable EasyEDA loader (Tier 5).
            use_digikey: Enable DigiKey loader (Tier 6).
            use_mouser: Enable Mouser loader (Tier 7).
            use_ic_data: Enable ic_data JSON store lookup (Tier 2).
        """
        self._reg = component_reg
        self._kicad = kicad_lib
        self._cache = cache or SymbolCache()
        self._use_dk = use_digikey
        self._use_mouser = use_mouser
        self._use_easyeda = use_easyeda
        self._use_ic_data = use_ic_data

    def resolve(
        self,
        mpn: str,
        *,
        item: dict[str, Any] | None = None,
        category: str = "digital",
    ) -> tuple[ComponentDef | None, str]:
        """Resolve an MPN through the full 7-tier chain.

        Returns (ComponentDef | None, source_str) where source_str is one of:
        - "registry" (Tier 1)
        - "ic_data" (Tier 2: JSON store, hot-loadable via register_ic)
        - "kicad" (Tier 3)
        - "cache" (Tier 4: rebuilt from cached metadata)
        - "easyeda" (Tier 5: full symbol via LCSC)
        - "digikey" (Tier 6: stub with footprint)
        - "mouser" (Tier 7: stub with footprint)
        - "unresolved" (all tiers exhausted)

        Once an MPN fails through every tier in this process, the answer is
        recorded in a class-level negative cache so subsequent calls return
        immediately without hitting remote APIs again. A design with N
        identical unresolvable components therefore incurs 1 lookup, not N.
        Transient API flaps stay unresolved for the rest of the process —
        call :meth:`clear_unresolved_cache` to re-enable retries.

        Args:
            mpn: Manufacturer Part Number to resolve.
            item: Optional dict from YAML spec (unused for now).
            category: Component category for KiCad lib fallback (e.g., "digital").

        Returns:
            Tuple of (ComponentDef or None, source string).
        """
        # Fast path: MPN already failed through every tier earlier in this
        # process. Skip the chain entirely.
        if mpn in SymbolResolver._unresolved_cache:
            return None, "unresolved"

        # Tier 1: Custom registry
        if self._reg:
            comp = self._reg.get(mpn)
            if comp:
                log.info("Resolved %s via registry", mpn)
                return comp, "registry"

        # Tier 2: ic_data JSON store (user-curated + template-extracted)
        if self._use_ic_data:
            comp = self._resolve_ic_data(mpn)
            if comp:
                log.info("Resolved %s via ic_data", mpn)
                return comp, "ic_data"

        # Tier 3: KiCad library
        if self._kicad:
            comp = self._kicad.get_component(mpn, category)
            if comp:
                log.info("Resolved %s via kicad lib", mpn)
                return comp, "kicad"

        # Tier 4: SymbolCache (rebuild from cached index entry)
        cached = self._cache.get(mpn)
        if cached:
            # Rebuild ComponentDef from cached metadata
            comp = self._rebuild_from_cache(mpn, cached)
            log.info("Resolved %s via cache (source=%s)", mpn, cached.get("source", "unknown"))
            return comp, "cache"

        # Tier 5: EasyEDA (full symbol via LCSC)
        if self._use_easyeda:
            comp = self._resolve_easyeda(mpn)
            if comp:
                log.info("Resolved %s via easyeda", mpn)
                return comp, "easyeda"

        # Tier 6: DigiKey (stub with footprint)
        if self._use_dk:
            comp = self._resolve_digikey(mpn)
            if comp:
                log.info("Resolved %s via digikey", mpn)
                return comp, "digikey"

        # Tier 6: Mouser (stub with footprint)
        if self._use_mouser:
            comp = self._resolve_mouser(mpn)
            if comp:
                log.debug("Resolved %s via mouser", mpn)
                return comp, "mouser"

        # All tiers failed — record so we don't retry this MPN in the
        # same process. Tests can reset via clear_unresolved_cache().
        SymbolResolver._unresolved_cache.add(mpn)
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

    def _rebuild_from_cache(self, mpn: str, cached: dict[str, Any]) -> ComponentDef | None:
        """Rebuild a ComponentDef from cached metadata.

        If the cache entry carries a full pin topology (``pins`` list, optional
        ``pin_nets`` / ``power_pins`` / ``bypass_caps`` / ``straps``), the
        resulting component is returned as trusted (``pinout_source="explicit"``)
        so downstream placement uses the real pin map. If the cache only
        carries distributor metadata (footprint + description + MPN), the
        component is returned as a stub (``pinout_source="stub"``) so the
        validator's ``pinout-source`` check blocks generation until the user
        supplies an explicit ``pin_map`` or sets ``pinout_verified: true``.
        This mirrors the DigiKey / Mouser stub path.

        Args:
            mpn: Manufacturer Part Number.
            cached: Dict from SymbolCache.get() with source, footprint, etc.

        Returns:
            ComponentDef with cached fields populated. Never returns a silently
            routed 2-pin passive for a multi-pin part — stubs are marked so the
            validator can fail closed.
        """
        from .component_db import BypassCap, ComponentDef, PinDef, PowerReq, StrapConfig

        raw_pins = cached.get("pins") or []
        pins: list[PinDef] = []
        for pin_payload in raw_pins:
            if isinstance(pin_payload, dict):
                pins.append(
                    PinDef(
                        number=str(pin_payload.get("number", "")),
                        name=str(pin_payload.get("name", "~")),
                        electrical_type=str(pin_payload.get("electrical_type", "passive")),
                        side=str(pin_payload.get("side", "L")),
                    )
                )
            elif isinstance(pin_payload, (list, tuple)) and len(pin_payload) == 4:
                pins.append(PinDef(*[str(x) for x in pin_payload]))

        pinout_source = "explicit" if pins else "stub"
        if not pins:
            # No pin topology in cache — mark as stub and emit minimal
            # placeholders. Validator will reject these unless the user
            # explicitly acknowledges the pinout via YAML spec.
            pins = [PinDef("1", "~", "passive", "L"), PinDef("2", "~", "passive", "R")]

        bypass_caps: list[BypassCap] = []
        for raw in cached.get("bypass_caps", []) or []:
            if isinstance(raw, dict):
                try:
                    bypass_caps.append(
                        BypassCap(
                            pin=str(raw.get("pin", "")),
                            net=str(raw.get("net", "")),
                            gnd_net=str(raw.get("gnd_net", "GND")),
                            value=str(raw.get("value", "")),
                            footprint=str(raw.get("footprint", "")),
                            role=str(raw.get("role", "decoupling")),
                            presentation=str(raw.get("presentation", "topology_local")),
                        )
                    )
                except (TypeError, ValueError) as exc:
                    log.debug("Cache bypass cap decode failed for %s: %s", mpn, exc)

        straps: list[StrapConfig] = []
        for raw in cached.get("straps", []) or []:
            if isinstance(raw, dict):
                try:
                    straps.append(
                        StrapConfig(
                            pin=str(raw.get("pin", "")),
                            net=str(raw.get("net", "")),
                            rail=str(raw.get("rail", "")),
                            value=str(raw.get("value", "")),
                            footprint=str(raw.get("footprint", "")),
                            role=str(raw.get("role", "pull_up")),
                            presentation=str(raw.get("presentation", "topology_local")),
                        )
                    )
                except (TypeError, ValueError) as exc:
                    log.debug("Cache strap decode failed for %s: %s", mpn, exc)

        power_reqs: list[PowerReq] = []
        for raw in cached.get("power_reqs", []) or []:
            if isinstance(raw, dict):
                try:
                    power_reqs.append(
                        PowerReq(
                            net=str(raw.get("net", "")),
                            voltage=float(raw.get("voltage", 0.0)),
                            max_current_ma=float(raw.get("max_current_ma", raw.get("current_ma", 0.0))),
                        )
                    )
                except (TypeError, ValueError) as exc:
                    log.debug("Cache power_req decode failed for %s: %s", mpn, exc)

        return ComponentDef(
            mpn=mpn,
            ref_prefix=str(cached.get("ref_prefix", "U")),
            value=str(cached.get("value", mpn)),
            footprint=str(cached.get("footprint", "")),
            description=str(cached.get("description", "")),
            category=str(cached.get("category", "digital")),
            source_manufacturer=str(cached.get("manufacturer", "")),
            digikey_pn=str(cached.get("digikey_pn", "")),
            lcsc_pn=str(cached.get("lcsc", "")),
            features=list(cached.get("features", []) or []),
            annotations=[f"CACHED: from {cached.get('source', 'unknown')} via symbol cache"],
            pins=pins,
            pin_nets=dict(cached.get("pin_nets", {}) or {}),
            power_pins=dict(cached.get("power_pins", {}) or {}),
            power_reqs=power_reqs,
            bypass_caps=bypass_caps,
            straps=straps,
            explicit_no_connects=set(cached.get("explicit_no_connects", []) or []),
            pinout_source=pinout_source,
        )

    # Module-level once-per-session cache of credential warnings so a
    # multi-component run doesn't emit the same "DigiKey skipped" line N
    # times. (Sprint 37 Task 156.)
    _cred_warned: set[str] = set()

    # Per-process negative cache of MPNs that exhausted every tier.
    # A design with 12 identical unresolvable parts triggers 1 lookup,
    # not 12. (Sprint 41 Task 175.) Cleared via clear_unresolved_cache().
    _unresolved_cache: set[str] = set()

    @classmethod
    def clear_unresolved_cache(cls) -> None:
        """Drop the negative-resolution cache so retries hit the tier chain.

        Tests and long-running processes that need to re-check after a
        transient remote-API failure can call this to force a full
        re-resolve on the next call.
        """
        cls._unresolved_cache.clear()

    @classmethod
    def _warn_credential_missing_once(cls, tier: str, missing: tuple[str, ...]) -> None:
        if tier in cls._cred_warned:
            return
        cls._cred_warned.add(tier)
        missing_text = ", ".join(missing)
        log.info(
            "%s tier skipped: %s not set. Run 'circuit-weaver doctor' to configure.",
            tier,
            missing_text,
        )

    def _resolve_ic_data(self, mpn: str) -> ComponentDef | None:
        """Tier 2: Try the ic_data JSON store.

        Looks up ``mpn`` in the unified ic_data database (bundled JSON files
        plus any user-registered entries) and converts the matched entry to
        a ``ComponentDef``.

        Args:
            mpn: Manufacturer Part Number.

        Returns:
            ComponentDef from JSON data, or None if the MPN is not in the
            store or the entry lacks a usable ``pins`` list.
        """
        try:
            from .ic_data import get_ic_data, ic_data_to_component_def
        except ImportError:
            log.debug("ic_data module unavailable")
            return None

        data = get_ic_data(mpn)
        if not data:
            return None
        comp = ic_data_to_component_def(mpn, data)
        return comp

    def _resolve_easyeda(self, mpn: str) -> ComponentDef | None:
        """Tier 5: Try LCSC-backed EasyEDA full symbol.

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
                    # Cache the full component (pins + power map) so the next
                    # session can reconstruct a trusted ComponentDef instead of
                    # degrading to a 2-pin stub.
                    from .symbol_cache import component_def_to_cache_payload

                    self._cache.put(
                        mpn,
                        component_def_to_cache_payload(
                            comp,
                            source="easyeda",
                            lcsc=lcsc_code,
                            manufacturer=lcsc_data.get("manufacturer", ""),
                        ),
                    )
                    return comp
        except Exception as exc:
            log.debug("EasyEDA fetch failed for LCSC %s: %s", lcsc_code, exc)

        return None

    def _resolve_digikey(self, mpn: str) -> ComponentDef | None:
        """Tier 6: Try DigiKey loader (lazy import).

        Args:
            mpn: Manufacturer Part Number.

        Returns:
            ComponentDef stub from DigiKey, or None if unavailable.
        """
        missing = tuple(name for name in ("DIGIKEY_CLIENT_ID", "DIGIKEY_CLIENT_SECRET") if not _get_credential(name))
        if missing:
            self._warn_credential_missing_once("DigiKey", missing)
            return None

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
        """Tier 7: Try Mouser loader (lazy import).

        Args:
            mpn: Manufacturer Part Number.

        Returns:
            ComponentDef stub from Mouser, or None if unavailable.
        """
        if not _get_credential("MOUSER_SEARCH_API_KEY"):
            self._warn_credential_missing_once("Mouser", ("MOUSER_SEARCH_API_KEY",))
            return None

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
