"""Extract structured metadata from PDF datasheets.

Requires: pypdf (optional). Falls back gracefully if not installed.

Usage:
    from circuit_weaver.datasheet_parser import extract_specs, parse_datasheet
    specs = parse_datasheet("datasheets/TPS61023DRLR.pdf")
"""

from __future__ import annotations

import json
import logging
import re
import time
from pathlib import Path

log = logging.getLogger(__name__)


def _try_import_pypdf():
    try:
        import pypdf

        return pypdf
    except ImportError:
        return None


_PATTERNS = {
    "theta_ja": [
        re.compile(r"[θΘ]\s*JA\s*[=:≈]\s*([\d.]+)\s*°?C/W", re.IGNORECASE),
        re.compile(r"Junction.to.Ambient\s*[=:]\s*([\d.]+)\s*°?C/W", re.IGNORECASE),
        re.compile(r"R[θΘ]JA\s*[=:]\s*([\d.]+)", re.IGNORECASE),
        re.compile(r"Thermal Resistance.*?Junction.*?Ambient.*?([\d.]+)\s*°?C/W", re.IGNORECASE),
    ],
    "theta_jc": [
        re.compile(r"[θΘ]\s*JC\s*[=:≈]\s*([\d.]+)\s*°?C/W", re.IGNORECASE),
        re.compile(r"Junction.to.Case\s*[=:]\s*([\d.]+)\s*°?C/W", re.IGNORECASE),
    ],
    "pdiss_max_w": [
        re.compile(r"(?:Maximum\s+)?Power\s+Dissipation\s*[=:]\s*([\d.]+)\s*W\b", re.IGNORECASE),
    ],
    "pdiss_max_mw": [
        re.compile(r"(?:Maximum\s+)?Power\s+Dissipation\s*[=:]\s*([\d.]+)\s*mW", re.IGNORECASE),
    ],
    "tj_max": [
        re.compile(r"(?:Maximum\s+)?Junction\s+Temp(?:erature)?\s*[=:]\s*[+-]?([\d.]+)\s*°?C", re.IGNORECASE),
    ],
    "vin_max": [
        re.compile(r"(?:Input|Supply)\s+Voltage\s*[=:]\s*[\d.]+\s*(?:to|–|-)\s*([\d.]+)\s*V", re.IGNORECASE),
    ],
    "vout_nom": [
        re.compile(r"Output\s+Voltage\s*[=:]\s*([\d.]+)\s*V", re.IGNORECASE),
    ],
    "iq_ua": [
        re.compile(r"Quiescent\s+Current\s*[=:]\s*([\d.]+)\s*[µu]A", re.IGNORECASE),
    ],
    "fsw_mhz": [
        re.compile(r"Switching\s+Frequency\s*[=:]\s*([\d.]+)\s*MHz", re.IGNORECASE),
    ],
    "fsw_khz": [
        re.compile(r"Switching\s+Frequency\s*[=:]\s*([\d.]+)\s*kHz", re.IGNORECASE),
    ],
}

_PASSIVE_PATTERNS = {
    "voltage_rating": [re.compile(r"Rated\s+Voltage\s*[=:]\s*([\d.]+)\s*V", re.IGNORECASE)],
    "tolerance_pct": [re.compile(r"Tolerance\s*[=:]\s*[±]?([\d.]+)\s*%", re.IGNORECASE)],
    "temp_coeff": [re.compile(r"Temperature\s+Coefficient\s*[=:]\s*([\w]+)", re.IGNORECASE)],
}

# ---------------------------------------------------------------------------
# T234 — normalized pin / interface schema extraction.
#
# Datasheet "Pin Functions" tables commonly follow a
# ``<number> <NAME> <I/O-type> <description>`` row shape. Rows matched here
# are converted into the same normalized fields the EasyEDA ingest emits
# (``pins``, ``pin_roles``, ``pin_vdd`` / ``pin_gnd`` power domains,
# ``explicit_no_connects``, ``debug_pins``), so datasheet-derived parts flow
# through topology builders without per-part Python.
# ---------------------------------------------------------------------------

_PIN_ROW_RE = re.compile(
    r"^\s*(\d{1,3})\s+([A-Z][A-Za-z0-9_/#+.\-~]{0,23})\s+(I/O|IO|I|O|P|PWR|G|GND|S|A|NC)\b",
    re.MULTILINE,
)

_PIN_TYPE_MAP = {
    "I": "input",
    "O": "output",
    "I/O": "bidirectional",
    "IO": "bidirectional",
    "P": "power_in",
    "PWR": "power_in",
    "S": "power_in",
    "G": "power_in",
    "GND": "power_in",
    "A": "passive",
    "NC": "no_connect",
}

_GND_PIN_NAME_RE = re.compile(r"^(GND|VSS\d*|AGND|DGND|PGND|SGND|EPAD|EP|VEE)$", re.IGNORECASE)
_SUPPLY_PIN_NAME_RE = re.compile(r"^(VDD\w*|VCC\w*|VIN\w*|AVDD\w*|DVDD\w*|VBAT|VBUS|V\+)$", re.IGNORECASE)
_NC_PIN_NAME_RE = re.compile(r"^(NC|DNC|N\.?C\.?|RESERVED|~)$", re.IGNORECASE)
_DEBUG_PIN_NAME_RE = re.compile(
    r"^(TEST\w*|DEBUG\w*|SWDIO|SWCLK|SWO|TDI|TDO|TMS|TCK|TRST#?|NTRST|JTAG\w*)$",
    re.IGNORECASE,
)

_RECOMMENDED_BYPASS_PATTERNS = [
    # "... a 0.1 µF ceramic bypass capacitor ..." / "... 100 nF decoupling cap ..."
    re.compile(
        r"([\d.]+)\s*([µu]F|nF|pF)\s+(?:X\d[RS]\s+)?(?:ceramic\s+)?(?:bypass|decoupling)\s+cap",
        re.IGNORECASE,
    ),
    # "... bypass the VDD pin with a 0.1 µF capacitor ..."
    re.compile(
        r"(?:bypass|decouple)[^.\n]{0,60}?(?:with|using)\s+(?:a\s+)?([\d.]+)\s*([µu]F|nF|pF)",
        re.IGNORECASE,
    ),
]


def _parse_pin_table_text(text: str) -> list[dict]:
    """Extract normalized pin rows from datasheet text.

    Returns a list of ``{"number", "name", "type", "side"}`` dicts in the
    engine's normalized pin schema. Duplicate pin numbers keep the first
    occurrence (pin tables repeat across package variants).
    """
    pins: list[dict] = []
    seen: set[str] = set()
    for match in _PIN_ROW_RE.finditer(text or ""):
        number, name, raw_type = match.group(1), match.group(2), match.group(3)
        if number in seen:
            continue
        seen.add(number)
        etype = _PIN_TYPE_MAP.get(raw_type.upper(), "unspecified")
        # Name-based enrichment mirrors the EasyEDA ingest so both paths
        # normalize identically.
        if _GND_PIN_NAME_RE.match(name) or _SUPPLY_PIN_NAME_RE.match(name):
            etype = "power_in"
        elif _NC_PIN_NAME_RE.match(name):
            etype = "no_connect"
        pins.append({"number": number, "name": name, "type": etype, "side": "L"})
    return pins


def _normalize_pin_schema(pins: list[dict]) -> dict:
    """Derive normalized interface fields from extracted pins.

    Emits the shared vendor-agnostic contract consumed by topology builders:
    ``pin_roles`` (canonical role -> pin number), ``pin_vdd`` / ``pin_gnd``
    power-domain lists, ``power_domains`` (distinct supply names),
    ``explicit_no_connects``, and ``debug_pins`` (optional pins that are
    safe to leave unrouted).
    """
    from .component_db import PinDef, infer_pin_roles_from_pins

    if not pins:
        return {}

    pin_defs = [PinDef(p["number"], p["name"], p["type"], p.get("side", "L")) for p in pins]
    out: dict = {"pins": pins}

    vdd_pins: list[str] = []
    gnd_pins: list[str] = []
    domains: list[str] = []
    ncs: list[str] = []
    debug: list[str] = []
    for p in pins:
        name = p["name"]
        if _GND_PIN_NAME_RE.match(name):
            gnd_pins.append(p["number"])
        elif _SUPPLY_PIN_NAME_RE.match(name):
            vdd_pins.append(p["number"])
            base = name.upper()
            if base not in domains:
                domains.append(base)
        elif _NC_PIN_NAME_RE.match(name) or p["type"] == "no_connect":
            ncs.append(p["number"])
        elif _DEBUG_PIN_NAME_RE.match(name):
            debug.append(p["number"])

    roles = infer_pin_roles_from_pins(pin_defs)
    if roles:
        out["pin_roles"] = roles
    if vdd_pins:
        out["pin_vdd"] = vdd_pins
    if gnd_pins:
        out["pin_gnd"] = gnd_pins
    if domains:
        out["power_domains"] = domains
    if ncs:
        out["explicit_no_connects"] = ncs
    if debug:
        out["debug_pins"] = debug
    return out


def _extract_recommended_bypass(text: str) -> list[dict]:
    """Extract datasheet-recommended bypass capacitors, if stated.

    Returns entries in the ``recommended_bypass`` schema consumed by
    :func:`component_db.auto_generate_bypass_caps`:
    ``[{"net": "VDD", "value": "100nF", "count": 1}]``.
    """
    for pattern in _RECOMMENDED_BYPASS_PATTERNS:
        match = pattern.search(text or "")
        if not match:
            continue
        try:
            value = float(match.group(1))
        except ValueError:
            continue
        unit = match.group(2).replace("µ", "u")
        unit = "uF" if unit.lower() == "uf" else unit.lower().replace("f", "F")
        # Normalize sub-unity microfarads: 0.1uF -> 100nF
        if unit == "uF" and value < 1:
            value, unit = value * 1000, "nF"
        return [{"net": "VDD", "value": f"{value:g}{unit}", "count": 1}]
    return []


def _apply_patterns(text: str, patterns: dict[str, list[re.Pattern]]) -> dict[str, float | str]:
    """Apply regex patterns to text and return matched values."""
    results: dict[str, float | str] = {}
    for key, pattern_list in patterns.items():
        for pattern in pattern_list:
            match = pattern.search(text)
            if match:
                val = match.group(1)
                try:
                    results[key] = float(val)
                except ValueError:
                    results[key] = val
                break
    return results


def parse_datasheet_text(text: str) -> dict:
    """Extract structured metadata from raw datasheet text.

    Pure-text core of :func:`parse_datasheet`, exposed so the ingest can be
    tested (and reused by non-PDF sources) without pypdf. Emits scalar specs
    plus, when a pin-function table is recognized, the normalized schema
    fields shared with the EasyEDA ingest: ``pins``, ``pin_roles``,
    ``pin_vdd`` / ``pin_gnd``, ``power_domains``, ``explicit_no_connects``,
    ``debug_pins``, and ``recommended_bypass``.
    """
    ic_specs = _apply_patterns(text, _PATTERNS)

    if "pdiss_max_mw" in ic_specs and "pdiss_max_w" not in ic_specs:
        ic_specs["pdiss_max_w"] = ic_specs.pop("pdiss_max_mw") / 1000.0
    elif "pdiss_max_mw" in ic_specs:
        del ic_specs["pdiss_max_mw"]

    if "fsw_khz" in ic_specs and "fsw_mhz" not in ic_specs:
        ic_specs["fsw_mhz"] = ic_specs.pop("fsw_khz") / 1000.0
    elif "fsw_khz" in ic_specs:
        del ic_specs["fsw_khz"]

    passive_specs = _apply_patterns(text, _PASSIVE_PATTERNS)
    result = {**ic_specs, **passive_specs}

    # T234 — normalized pin/interface schema propagation.
    result.update(_normalize_pin_schema(_parse_pin_table_text(text)))
    recommended = _extract_recommended_bypass(text)
    if recommended:
        result["recommended_bypass"] = recommended
    return result


def parse_datasheet(pdf_path: str | Path) -> dict:
    """Parse a single PDF datasheet and extract structured metadata."""
    pdf_path = Path(pdf_path)
    if not pdf_path.exists():
        return {}

    pypdf = _try_import_pypdf()
    if pypdf is None:
        return {"status": "no_pypdf", "file": pdf_path.name}

    try:
        reader = pypdf.PdfReader(str(pdf_path))
        pages_to_read = min(len(reader.pages), 10)
        text = "\n".join(reader.pages[i].extract_text() or "" for i in range(pages_to_read))
    except Exception:
        return {"status": "no_text", "file": pdf_path.name}

    if not text.strip():
        return {"status": "no_text", "file": pdf_path.name}

    result = parse_datasheet_text(text)
    result["file"] = pdf_path.name
    result["extracted_timestamp"] = time.strftime("%Y-%m-%dT%H:%M:%SZ")
    return result


def extract_specs(datasheets_dir: str | Path, output_dir: str | Path) -> dict:
    """Batch-extract specs from all PDFs in a datasheets directory."""
    datasheets_dir = Path(datasheets_dir)
    output_dir = Path(output_dir)

    if not datasheets_dir.exists():
        return {"status": "error", "message": f"Datasheets directory not found: {datasheets_dir}"}

    if _try_import_pypdf() is None:
        return {"status": "error", "message": "pypdf not installed. Install with: pip install pypdf"}

    index_path = datasheets_dir / "index.json"
    index_data: dict = {}
    if index_path.exists():
        try:
            index_data = json.loads(index_path.read_text(encoding="utf-8"))
        except Exception:
            pass

    pdf_files = sorted(datasheets_dir.glob("*.pdf"))
    if not pdf_files:
        return {
            "status": "ok",
            "processed": 0,
            "extracted": 0,
            "failed": 0,
            "skipped": 0,
            "output_file": "",
            "warnings": ["No PDF files found"],
        }

    output_file = output_dir / "metadata.json"
    existing: dict = {}
    if output_file.exists():
        try:
            existing = json.loads(output_file.read_text(encoding="utf-8"))
        except Exception:
            pass

    metadata: dict = {}
    warnings: list[str] = []
    extracted = 0
    failed_count = 0
    skipped_count = 0

    for pdf in pdf_files:
        mpn = pdf.stem.replace("_", "/")
        if mpn in existing and existing[mpn].get("extracted_timestamp"):
            skipped_count += 1
            metadata[mpn] = existing[mpn]
            continue

        result = parse_datasheet(pdf)
        if not result or result.get("status") in ("no_text", "no_pypdf"):
            failed_count += 1
            warnings.append(f"Could not extract text from {pdf.name}")
            continue

        parts = index_data.get("parts", {})
        if mpn in parts:
            result["manufacturer"] = parts[mpn].get("manufacturer", "")
            result["description"] = parts[mpn].get("description", "")
            # T234 — vendor aliases are sourcing metadata, never behavior
            # selectors; propagate them so imported entries keep their
            # distributor cross-references.
            aliases = parts[mpn].get("aliases") or []
            if aliases:
                result["vendor_aliases"] = [str(a) for a in aliases if str(a or "").strip()]

        metadata[mpn] = result
        extracted += 1

    output_dir.mkdir(parents=True, exist_ok=True)
    output_file.write_text(json.dumps(metadata, indent=2, ensure_ascii=False), encoding="utf-8")

    return {
        "status": "ok",
        "processed": len(pdf_files),
        "extracted": extracted,
        "failed": failed_count,
        "skipped": skipped_count,
        "output_file": str(output_file),
        "warnings": warnings,
    }
