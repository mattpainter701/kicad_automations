"""Distributor-integrated component lookup.

Searches LCSC (free, no auth) then DigiKey (OAuth 2.0 client credentials)
for parametric data, datasheet URLs, and descriptions.  Results are cached
locally for 7 days to avoid repeated API calls.

Usage:
    from circuit_weaver.parts_lookup import PartsLookup
    lkp = PartsLookup()
    data = lkp.lookup("GRM155R71C104KA88D")
    url  = lkp.get_datasheet_url("GRM155R71C104KA88D")

Integration point:
    ``resolve_project_spec()`` / ``load_project()`` in project_spec.py can
    call ``enrich_component()`` when YAML resolution is run with
    ``enrich_parts=True``.
"""

from __future__ import annotations

import json
import logging
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from .component_db import ComponentDef

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Credential helpers
# ---------------------------------------------------------------------------

_SECRETS_PATH = Path(os.path.expanduser("~/.config/secrets.env"))
_CACHE_DIR = Path(os.path.expanduser("~/.cache/schematic_engine/parts"))
_CACHE_MAX_AGE = 7 * 24 * 3600  # 7 days in seconds
_HTTP_TIMEOUT = 15  # seconds


def _load_secrets_env() -> dict[str, str]:
    """Parse ``~/.config/secrets.env`` into a dict.

    Lines are ``KEY=VALUE``, comments (``#``) and blanks are skipped.
    Values are NOT shell-unquoted -- they're used as-is.
    """
    result: dict[str, str] = {}
    if not _SECRETS_PATH.exists():
        return result
    for line in _SECRETS_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, val = line.partition("=")
        result[key.strip()] = val.strip()
    return result


def _get_credential(name: str) -> str:
    """Return a credential from env vars, falling back to secrets.env."""
    val = os.environ.get(name, "")
    if val:
        return val
    secrets = _load_secrets_env()
    return secrets.get(name, "")


# ---------------------------------------------------------------------------
# HTTP helpers (urllib only, no external deps)
# ---------------------------------------------------------------------------


def _http_get_json(url: str, headers: dict[str, str] | None = None) -> Any:
    """GET a URL, return parsed JSON or None on error."""
    req = urllib.request.Request(url, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=_HTTP_TIMEOUT) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, urllib.error.HTTPError, OSError, json.JSONDecodeError) as exc:
        log.debug("GET %s failed: %s", url, exc)
        return None


def _http_post_json(
    url: str,
    body: dict,
    headers: dict[str, str] | None = None,
    form_encoded: bool = False,
) -> Any:
    """POST JSON (or form-encoded) to a URL, return parsed JSON or None."""
    hdrs = dict(headers or {})
    if form_encoded:
        data = urllib.parse.urlencode(body).encode("utf-8")
        hdrs.setdefault("Content-Type", "application/x-www-form-urlencoded")
    else:
        data = json.dumps(body).encode("utf-8")
        hdrs.setdefault("Content-Type", "application/json")
    req = urllib.request.Request(url, data=data, headers=hdrs, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=_HTTP_TIMEOUT) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, urllib.error.HTTPError, OSError, json.JSONDecodeError) as exc:
        log.debug("POST %s failed: %s", url, exc)
        return None


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------


def _cache_path(mpn: str) -> Path:
    """Return the on-disk cache path for an MPN (sanitised filename)."""
    safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in mpn)
    return _CACHE_DIR / f"{safe}.json"


def _read_cache(mpn: str) -> dict | None:
    """Return cached data if it exists and is less than 7 days old."""
    p = _cache_path(mpn)
    if not p.exists():
        return None
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    ts = raw.get("_cached_at", 0)
    if time.time() - ts > _CACHE_MAX_AGE:
        return None
    return raw


def _write_cache(mpn: str, data: dict) -> None:
    """Write lookup data to the on-disk cache."""
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    payload = dict(data)
    payload["_cached_at"] = time.time()
    try:
        _cache_path(mpn).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except OSError as exc:
        log.debug("Cache write failed for %s: %s", mpn, exc)


# ---------------------------------------------------------------------------
# LCSC search (free, no auth)
# ---------------------------------------------------------------------------

_LCSC_SEARCH_URL = "https://jlcsearch.tscircuit.com/api/search"


def get_unit_price(price_tiers: list[dict], qty: int) -> float | None:
    """Return unit price for the given quantity from price tiers.

    Args:
        price_tiers: List of {min_qty, max_qty, unit_price} dicts, sorted by min_qty.
        qty: Quantity to price.

    Returns:
        Unit price at the appropriate tier, or None if no tiers available.
    """
    if not price_tiers:
        return None

    # Find the tier that covers this quantity
    for tier in sorted(price_tiers, key=lambda t: t["min_qty"]):
        if tier["min_qty"] <= qty <= tier.get("max_qty", 9_999_999):
            return tier["unit_price"]

    # Quantity exceeds all tiers — return the last (highest quantity) tier
    return sorted(price_tiers, key=lambda t: t["min_qty"])[-1]["unit_price"]


def _search_lcsc(mpn: str) -> dict | None:
    """Search LCSC via the jlcsearch community API.

    Returns a normalised dict or None if nothing useful was found.
    """
    params = urllib.parse.urlencode({"q": mpn, "limit": "5", "full": "true"})
    url = f"{_LCSC_SEARCH_URL}?{params}"
    resp = _http_get_json(url)
    if not resp:
        return None

    components = resp.get("components") or []
    if not components:
        return None

    # Pick the best match: prefer exact MPN match
    best = None
    for comp in components:
        extra = comp.get("extra") or {}
        comp_mpn = extra.get("mpn", "") or comp.get("mfr", "")
        if comp_mpn.upper() == mpn.upper():
            best = comp
            break
    if best is None:
        best = components[0]

    extra = best.get("extra") or {}
    attrs = extra.get("attributes") or {}
    ds_obj = extra.get("datasheet") or {}
    mfr_obj = extra.get("manufacturer") or {}

    lcsc_code = extra.get("number", "")
    if not lcsc_code:
        raw_lcsc = best.get("lcsc")
        if raw_lcsc:
            lcsc_code = f"C{raw_lcsc}"

    # Parse price tiers from extra.prices
    raw_prices = extra.get("prices") or []
    price_tiers = []
    for tier in raw_prices:
        try:
            price_tiers.append(
                {
                    "min_qty": int(tier.get("min_qty", 1)),
                    "max_qty": int(tier.get("max_qty", 9999)),
                    "unit_price": float(tier.get("price", 0)),
                }
            )
        except (TypeError, ValueError):
            continue

    return {
        "source": "lcsc",
        "mpn": extra.get("mpn", "") or best.get("mfr", ""),
        "manufacturer": mfr_obj.get("name", "") if isinstance(mfr_obj, dict) else str(mfr_obj),
        "description": extra.get("description", "") or best.get("description", ""),
        "package": extra.get("package", "") or best.get("package", ""),
        "datasheet_url": ds_obj.get("pdf", "") if isinstance(ds_obj, dict) else "",
        "lcsc": lcsc_code,
        "attributes": attrs,
        "stock": extra.get("quantity", 0) or best.get("stock", 0),
        "basic": bool(best.get("basic", 0)),
        "price_tiers": price_tiers,
    }


# ---------------------------------------------------------------------------
# DigiKey search (OAuth 2.0 client credentials)
# ---------------------------------------------------------------------------

_DK_TOKEN_URL = "https://api.digikey.com/v1/oauth2/token"
_DK_SEARCH_URL = "https://api.digikey.com/products/v4/search/keyword"

# Module-level token cache (in-process only; token TTL is 10 min)
_dk_token: str = ""
_dk_token_expiry: float = 0.0


def _get_dk_token(client_id: str, client_secret: str) -> str | None:
    """Obtain or reuse a cached DigiKey OAuth 2.0 bearer token."""
    global _dk_token, _dk_token_expiry  # noqa: PLW0603
    if _dk_token and time.time() < _dk_token_expiry:
        return _dk_token

    resp = _http_post_json(
        _DK_TOKEN_URL,
        {
            "client_id": client_id,
            "client_secret": client_secret,
            "grant_type": "client_credentials",
        },
        form_encoded=True,
    )
    if not resp or "access_token" not in resp:
        log.debug("DigiKey token request failed: %s", resp)
        return None

    _dk_token = resp["access_token"]
    # Expire 60s early to avoid edge-case 401s
    _dk_token_expiry = time.time() + resp.get("expires_in", 600) - 60
    return _dk_token


def _search_digikey(mpn: str) -> dict | None:
    """Search DigiKey by MPN.  Requires API credentials.

    Returns a normalised dict or None.
    """
    client_id = _get_credential("DIGIKEY_CLIENT_ID")
    client_secret = _get_credential("DIGIKEY_CLIENT_SECRET")
    if not client_id or not client_secret:
        log.debug("DigiKey credentials not available, skipping")
        return None

    token = _get_dk_token(client_id, client_secret)
    if not token:
        return None

    headers = {
        "Authorization": f"Bearer {token}",
        "X-DIGIKEY-Client-Id": client_id,
    }
    body = {"Keywords": mpn, "Limit": 5}
    resp = _http_post_json(_DK_SEARCH_URL, body, headers=headers)
    if not resp:
        return None

    products = resp.get("Products") or resp.get("products") or []
    if not products:
        return None

    # Pick exact MPN match if available
    best = None
    for prod in products:
        prod_mpn = prod.get("ManufacturerProductNumber", "")
        if prod_mpn.upper() == mpn.upper():
            best = prod
            break
    if best is None:
        best = products[0]

    mfr = best.get("Manufacturer") or {}
    desc_obj = best.get("Description") or {}
    params = best.get("Parameters") or []

    # Build attributes dict from parametric data
    attrs: dict[str, str] = {}
    for p in params:
        name = p.get("ParameterText", "")
        val = p.get("ValueText", "")
        if name and val:
            attrs[name] = val

    # Get datasheet URL — normalise protocol-relative URLs
    ds_url = best.get("DatasheetUrl", "") or ""
    if ds_url.startswith("//"):
        ds_url = f"https:{ds_url}"

    return {
        "source": "digikey",
        "mpn": best.get("ManufacturerProductNumber", ""),
        "manufacturer": mfr.get("Name", "") if isinstance(mfr, dict) else str(mfr),
        "description": desc_obj.get("ProductDescription", "") if isinstance(desc_obj, dict) else str(desc_obj),
        "package": attrs.get("Package / Case", ""),
        "datasheet_url": ds_url,
        "digikey_pn": (best.get("ProductVariations") or [{}])[0].get("DigiKeyProductNumber", ""),
        "attributes": attrs,
        "stock": best.get("QuantityAvailable", 0),
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


class PartsLookup:
    """Distributor-integrated component lookup with local caching.

    Search chain: cache -> LCSC -> DigiKey.
    """

    def lookup(self, mpn: str) -> dict | None:
        """Look up a component by MPN.

        Returns a normalised dict with keys:
            source, mpn, manufacturer, description, package,
            datasheet_url, attributes, stock, (lcsc | digikey_pn)

        Returns None if no results from any source.
        """
        if not mpn or not mpn.strip():
            return None
        mpn = mpn.strip()

        # 1. Cache hit?
        cached = _read_cache(mpn)
        if cached is not None:
            return cached

        # 2. LCSC (free, no auth)
        data = _search_lcsc(mpn)
        if data and data.get("mpn"):
            _write_cache(mpn, data)
            return data

        # 3. DigiKey (requires credentials)
        data = _search_digikey(mpn)
        if data and data.get("mpn"):
            _write_cache(mpn, data)
            return data

        return None

    def get_datasheet_url(self, mpn: str) -> str | None:
        """Return the datasheet PDF URL for an MPN, or None."""
        data = self.lookup(mpn)
        if not data:
            return None
        url = data.get("datasheet_url", "")
        return url if url else None

    def lookup_by_lcsc(self, lcsc_pn: str) -> dict | None:
        """Look up a component by LCSC part number.

        Args:
            lcsc_pn: LCSC part number (e.g., "C14663" or "14663")

        Returns:
            Normalised dict from LCSC API or None if not found.
        """
        if not lcsc_pn or not lcsc_pn.strip():
            return None
        lcsc_pn = lcsc_pn.strip()
        # Ensure it starts with 'C' for the search query
        query = lcsc_pn if lcsc_pn.startswith("C") else f"C{lcsc_pn}"
        return self.lookup(query)


# ---------------------------------------------------------------------------
# ComponentDef enrichment
# ---------------------------------------------------------------------------


def enrich_component(comp: ComponentDef, data: dict) -> None:
    """Fill empty ComponentDef fields from distributor lookup data.

    Only overwrites fields that are currently empty/blank.
    Does not touch pin definitions, bypass caps, straps, or wiring.
    """
    if not comp.description and data.get("description"):
        comp.description = data["description"]

    if not comp.source_manufacturer and data.get("manufacturer"):
        comp.source_manufacturer = data["manufacturer"]

    # Store the datasheet URL in annotations for traceability
    ds_url = data.get("datasheet_url", "")
    if ds_url:
        ds_note = f"Datasheet: {ds_url}"
        if ds_note not in comp.annotations:
            comp.annotations.append(ds_note)

    # Populate source fields if blank
    if not comp.source_description and data.get("description"):
        comp.source_description = data["description"]

    if not comp.source_mpn:
        comp.source_mpn = data.get("mpn", "")

    # Populate first-class distributor PN fields
    lcsc = data.get("lcsc", "")
    if lcsc and not comp.lcsc_pn:
        comp.lcsc_pn = lcsc

    dk_pn = data.get("digikey_pn", "")
    if dk_pn and not comp.digikey_pn:
        comp.digikey_pn = dk_pn

    # Also store in features for backward compatibility
    if lcsc:
        lcsc_tag = f"LCSC:{lcsc}"
        if lcsc_tag not in comp.features:
            comp.features.append(lcsc_tag)

    # Package hint — can inform footprint selection if footprint is empty
    pkg = data.get("package", "")
    if pkg:
        pkg_tag = f"Package:{pkg}"
        if pkg_tag not in comp.features:
            comp.features.append(pkg_tag)


if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.DEBUG)
    mpn_arg = sys.argv[1] if len(sys.argv) > 1 else "GRM155R71C104KA88D"
    lkp = PartsLookup()
    result = lkp.lookup(mpn_arg)
    if result:
        # Remove internal cache timestamp for display
        display = {k: v for k, v in result.items() if not k.startswith("_")}
        print(json.dumps(display, indent=2, ensure_ascii=False))
    else:
        print(f"No results for {mpn_arg}")
