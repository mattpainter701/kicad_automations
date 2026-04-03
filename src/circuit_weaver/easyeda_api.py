"""EasyEDA API client — fetch component symbols by LCSC part number.

Queries EasyEDA's public API (no authentication required) to retrieve
symbol shape data, footprint data, and component metadata for any part
in JLCPCB/LCSC's 300K+ component library.

Pipeline:
    1. GET /api/products/{lcsc_id}/svgs → list of component UUIDs
    2. GET /api/components/{uuid}       → shape strings + metadata

Usage:
    from circuit_weaver.easyeda_api import fetch_easyeda_component
    data = fetch_easyeda_component("C14663")
    # Returns dict with symbol shapes, footprint shapes, metadata
"""

from __future__ import annotations

import gzip
import json
import logging
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_EASYEDA_BASE = "https://easyeda.com/api"
_JLCPCB_SEARCH_URL = "https://jlcpcb.com/api/overseas/smt/selectSmtComponentLibrary"

_CACHE_DIR = Path.home() / ".cache" / "schematic_engine" / "easyeda"
_CACHE_MAX_AGE = 7 * 24 * 3600  # 7 days

_HTTP_TIMEOUT = 20  # seconds

_HEADERS = {
    "User-Agent": "circuit-weaver/0.6 (KiCad automation)",
    "Accept": "application/json",
    "Accept-Encoding": "gzip",
}


# ---------------------------------------------------------------------------
# HTTP helpers (stdlib only)
# ---------------------------------------------------------------------------


def _http_get(url: str) -> bytes | None:
    """GET a URL and return raw bytes, handling gzip."""
    req = urllib.request.Request(url, headers=_HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=_HTTP_TIMEOUT) as resp:
            data = resp.read()
            if resp.headers.get("Content-Encoding") == "gzip":
                data = gzip.decompress(data)
            return data
    except (urllib.error.URLError, urllib.error.HTTPError, OSError) as exc:
        log.debug("GET %s failed: %s", url, exc)
        return None


def _http_get_json(url: str) -> dict | list | None:
    """GET a URL and return parsed JSON."""
    raw = _http_get(url)
    if raw is None:
        return None
    try:
        return json.loads(raw.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        log.debug("JSON parse failed for %s: %s", url, exc)
        return None


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------


def _cache_path(lcsc_id: str) -> Path:
    safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in lcsc_id)
    return _CACHE_DIR / f"{safe}.json"


def _read_cache(lcsc_id: str) -> dict | None:
    p = _cache_path(lcsc_id)
    if not p.exists():
        return None
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    if time.time() - raw.get("_cached_at", 0) > _CACHE_MAX_AGE:
        return None
    return raw


def _write_cache(lcsc_id: str, data: dict) -> None:
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    payload = dict(data)
    payload["_cached_at"] = time.time()
    try:
        _cache_path(lcsc_id).write_text(
            json.dumps(payload, ensure_ascii=False),
            encoding="utf-8",
        )
    except OSError as exc:
        log.debug("Cache write failed for %s: %s", lcsc_id, exc)


# ---------------------------------------------------------------------------
# EasyEDA API
# ---------------------------------------------------------------------------


def _normalize_lcsc_id(lcsc_id: str) -> str:
    """Ensure LCSC ID has the 'C' prefix."""
    lcsc_id = lcsc_id.strip()
    if lcsc_id.startswith("C") and lcsc_id[1:].isdigit():
        return lcsc_id
    if lcsc_id.isdigit():
        return f"C{lcsc_id}"
    return lcsc_id


def _fetch_component_uuids(lcsc_id: str) -> list[str] | None:
    """Fetch the list of EasyEDA component UUIDs for an LCSC part.

    Returns a list where the last UUID is the footprint and all
    preceding UUIDs are symbol units (single-unit parts have 1 symbol UUID).
    """
    url = f"{_EASYEDA_BASE}/products/{lcsc_id}/svgs"
    resp = _http_get_json(url)
    if not resp:
        return None

    # Response is {"success": true, "result": [{"uuid": "...", ...}, ...]}
    # or a list of dicts directly
    if isinstance(resp, dict):
        result = resp.get("result")
        if not result:
            return None
    elif isinstance(resp, list):
        result = resp
    else:
        return None

    uuids = []
    for item in result:
        if isinstance(item, dict):
            uuid = item.get("uuid") or item.get("component_uuid", "")
            if uuid:
                uuids.append(uuid)
        elif isinstance(item, str):
            uuids.append(item)

    return uuids if uuids else None


def _fetch_component_data(uuid: str) -> dict | None:
    """Fetch full component data (shapes, metadata) for a single UUID."""
    url = f"{_EASYEDA_BASE}/components/{uuid}"
    resp = _http_get_json(url)
    if not resp:
        return None

    # Response: {"success": true, "result": {...}} or direct dict
    if isinstance(resp, dict) and "result" in resp:
        return resp["result"]
    return resp


def fetch_easyeda_component(lcsc_id: str, use_cache: bool = True) -> dict | None:
    """Fetch full component data from EasyEDA for an LCSC part number.

    Returns a dict with:
        - title: str — component name
        - prefix: str — reference prefix (U, R, C, etc.)
        - description: str
        - lcsc_id: str
        - mpn: str — manufacturer part number
        - manufacturer: str
        - package: str
        - symbol_shapes: list[list[str]] — shape strings per unit
        - footprint_shapes: list[str] — footprint shape strings
        - datasheet_url: str

    Returns None if the component can't be found or fetched.
    """
    lcsc_id = _normalize_lcsc_id(lcsc_id)

    # Check cache
    if use_cache:
        cached = _read_cache(lcsc_id)
        if cached is not None:
            return cached

    # Step 1: Get UUIDs
    uuids = _fetch_component_uuids(lcsc_id)
    if not uuids:
        log.info("No EasyEDA data found for %s", lcsc_id)
        return None

    # Step 2: Fetch each UUID's data
    # Convention: last UUID = footprint, others = symbol units.
    # Fail closed if any UUID fetch is missing so callers never get a
    # silently truncated multi-unit symbol.
    symbol_data_list = []
    footprint_data = None

    for i, uuid in enumerate(uuids):
        comp_data = _fetch_component_data(uuid)
        if not comp_data:
            log.warning("Incomplete EasyEDA response for %s: missing UUID %s", lcsc_id, uuid)
            return None

        if i == len(uuids) - 1:
            footprint_data = comp_data
        else:
            symbol_data_list.append(comp_data)

    if not symbol_data_list:
        log.info("No symbol data returned for %s", lcsc_id)
        return None

    # Extract metadata from the first symbol unit
    first = symbol_data_list[0]
    data_str = first.get("dataStr") or {}
    if isinstance(data_str, str):
        try:
            data_str = json.loads(data_str)
        except json.JSONDecodeError:
            data_str = {}
    head = data_str.get("head") or {}
    # c_para lives inside dataStr.head (not at the top level)
    c_para = head.get("c_para") or first.get("c_para") or {}

    # Build symbol shape lists (one per unit)
    symbol_shapes = []
    for sd in symbol_data_list:
        ds = sd.get("dataStr") or {}
        if isinstance(ds, str):
            try:
                ds = json.loads(ds)
            except json.JSONDecodeError:
                ds = {}
        shapes = ds.get("shape") or []
        if not isinstance(shapes, list) or not shapes:
            log.warning("Incomplete EasyEDA symbol data for %s: missing shape list", lcsc_id)
            return None
        symbol_shapes.append(shapes)

    # Build footprint shapes
    fp_shapes = []
    if footprint_data:
        fp_ds = footprint_data.get("dataStr") or {}
        if isinstance(fp_ds, str):
            try:
                fp_ds = json.loads(fp_ds)
            except json.JSONDecodeError:
                fp_ds = {}
        fp_shapes = fp_ds.get("shape") or []

    result = {
        "title": first.get("title", "") or c_para.get("name", ""),
        "prefix": c_para.get("pre", "U?").rstrip("?") or "U",
        "description": first.get("description", "") or c_para.get("des", ""),
        "lcsc_id": lcsc_id,
        "mpn": c_para.get("Manufacturer Part", "") or c_para.get("mpn", ""),
        "manufacturer": c_para.get("Manufacturer", "") or c_para.get("brand", ""),
        "package": c_para.get("package", ""),
        "datasheet_url": c_para.get("link", "") or c_para.get("datasheet", ""),
        "symbol_shapes": symbol_shapes,
        "footprint_shapes": fp_shapes,
    }

    # Cache the result
    if use_cache:
        _write_cache(lcsc_id, result)

    return result


def search_easyeda(query: str, limit: int = 10) -> list[dict]:
    """Search JLCPCB/LCSC component library by keyword.

    Returns a list of dicts with: lcsc_id, mpn, manufacturer, description, package.
    """
    # Use jlcsearch community API (same as parts_lookup.py)
    params = urllib.parse.urlencode({"q": query, "limit": str(limit), "full": "true"})
    url = f"https://jlcsearch.tscircuit.com/api/search?{params}"
    resp = _http_get_json(url)
    if not resp:
        return []

    components = resp.get("components") or []
    results = []
    for comp in components:
        extra = comp.get("extra") or {}
        lcsc_code = extra.get("number", "")
        if not lcsc_code:
            raw_lcsc = comp.get("lcsc")
            if raw_lcsc:
                lcsc_code = f"C{raw_lcsc}"

        mfr_obj = extra.get("manufacturer") or {}
        results.append(
            {
                "lcsc_id": lcsc_code,
                "mpn": extra.get("mpn", "") or comp.get("mfr", ""),
                "manufacturer": mfr_obj.get("name", "") if isinstance(mfr_obj, dict) else str(mfr_obj),
                "description": extra.get("description", "") or comp.get("description", ""),
                "package": extra.get("package", "") or comp.get("package", ""),
            }
        )

    return results


if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.DEBUG)
    lcsc_arg = sys.argv[1] if len(sys.argv) > 1 else "C14663"
    data = fetch_easyeda_component(lcsc_arg, use_cache=False)
    if data:
        # Print summary, not full shapes
        summary = {k: v for k, v in data.items() if k not in ("symbol_shapes", "footprint_shapes")}
        summary["symbol_units"] = len(data.get("symbol_shapes", []))
        summary["symbol_shape_count"] = sum(len(s) for s in data.get("symbol_shapes", []))
        summary["footprint_shape_count"] = len(data.get("footprint_shapes", []))
        print(json.dumps(summary, indent=2, ensure_ascii=False))
    else:
        print(f"No data for {lcsc_arg}")
