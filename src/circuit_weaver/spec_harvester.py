"""Unified datasheet + spec harvester for circuit designs.

Downloads datasheets and extracts structured parametric specs from distributor
APIs (LCSC, DigiKey) for every component in a design spec. Outputs:
  - datasheets/  directory with PDF files + index.json manifest
  - specs/       directory with structured JSON (thermal, passives, SI)

Usage:
    from circuit_weaver.spec_harvester import harvest_specs
    result = harvest_specs(spec, output_dir="./project")
"""

from __future__ import annotations

import json
import logging
import re
import time
from pathlib import Path

from .component_db import ComponentDef
from .mvp import compile_design_ir
from .parts_lookup import PartsLookup

log = logging.getLogger(__name__)

_DEFAULT_DELAY = 0.5


def _classify_component(comp: ComponentDef) -> str:
    """Classify a component as ic, passive, connector, crystal, or other."""
    prefix = comp.source_ref[:1].upper() if comp.source_ref else ""
    if prefix == "U":
        return "ic"
    if prefix in ("R", "C", "L"):
        return "passive"
    if prefix == "J":
        return "connector"
    if prefix in ("Y", "X"):
        return "crystal"
    if prefix in ("D", "Q"):
        return "semiconductor"
    return "other"


def _extract_passive_specs(comp: ComponentDef, lookup_data: dict | None) -> dict:
    """Extract specs for passive components from component data and API response."""
    specs: dict = {
        "type": "passive",
        "value": comp.value or "",
        "footprint": comp.footprint or "",
    }
    attrs = (lookup_data or {}).get("attributes", {})
    if attrs:
        for key in ("Capacitance", "Resistance", "Inductance"):
            if key in attrs:
                specs["primary_value"] = attrs[key]
        for key in ("Voltage Rated", "Voltage - Rated"):
            if key in attrs:
                specs["voltage_rating"] = attrs[key]
        if "Tolerance" in attrs:
            specs["tolerance"] = attrs["Tolerance"]
        if "Temperature Coefficient" in attrs:
            specs["temp_coeff"] = attrs["Temperature Coefficient"]
    return specs


def _extract_ic_specs(comp: ComponentDef, lookup_data: dict | None) -> dict:
    """Extract specs for ICs from API parametric data."""
    specs: dict = {
        "type": _guess_ic_type(comp),
        "mpn": comp.mpn,
    }
    attrs = (lookup_data or {}).get("attributes", {})
    if attrs:
        for key in ("Voltage - Supply", "Voltage - Input"):
            if key in attrs:
                specs["vin_range"] = attrs[key]
        for key in ("Voltage - Output", "Output Voltage"):
            if key in attrs:
                specs["vout"] = attrs[key]
        for key in ("Current - Output", "Current - Supply"):
            if key in attrs:
                specs["current"] = attrs[key]
        for key in ("Current - Quiescent (Iq)",):
            if key in attrs:
                specs["iq"] = attrs[key]
        if "Operating Temperature" in attrs:
            specs["temp_range"] = attrs["Operating Temperature"]
        if "Package / Case" in attrs:
            specs["package"] = attrs["Package / Case"]
    return specs


def _guess_ic_type(comp: ComponentDef) -> str:
    """Guess IC type from description or template."""
    desc = (comp.description or "").lower()
    mpn = (comp.mpn or "").lower()
    combined = f"{desc} {mpn}"
    if any(w in combined for w in ("buck", "step-down", "switching regulator")):
        return "buck_converter"
    if any(w in combined for w in ("boost", "step-up")):
        return "boost_converter"
    if any(w in combined for w in ("ldo", "linear regulator", "low-dropout")):
        return "ldo_regulator"
    if any(w in combined for w in ("mcu", "microcontroller", "stm32", "esp32", "atmega")):
        return "microcontroller"
    if any(w in combined for w in ("op amp", "opamp", "operational amplifier")):
        return "op_amp"
    if any(w in combined for w in ("sensor", "bme", "bmp", "ina")):
        return "sensor"
    return "ic"


def _download_datasheet(url: str, dest: Path, *, timeout: int = 30) -> bool:
    """Download a PDF datasheet. Returns True on success."""
    if not url or dest.exists():
        return dest.exists()
    try:
        import urllib.request

        headers = {"User-Agent": "Mozilla/5.0 (circuit-weaver spec-harvester)"}
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = resp.read()
        if not data[:5].startswith(b"%PDF"):
            return False
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        return True
    except Exception:
        return False


def harvest_specs(
    spec: dict,
    output_dir: str | Path = ".",
    *,
    skip_download: bool = False,
    delay: float = _DEFAULT_DELAY,
) -> dict:
    """Harvest datasheets and structured specs for all components in a design.

    Returns dict with status, counts, index, and warnings.
    """
    output_dir = Path(output_dir)
    datasheets_dir = output_dir / "datasheets"
    specs_dir = output_dir / "specs"

    try:
        compiled = compile_design_ir(spec)
    except Exception as e:
        return {"status": "error", "message": f"Failed to compile spec: {e}", "project": spec.get("project", "Unknown")}

    project_name = spec.get("project", "Unknown")
    components = compiled.components

    seen_mpns: dict[str, list[str]] = {}
    unique_components: list[ComponentDef] = []
    for comp in components:
        if not comp.source_ref:
            continue
        key = comp.mpn or comp.lcsc_pn or comp.value or ""
        if not key:
            continue
        if key in seen_mpns:
            seen_mpns[key].append(comp.source_ref)
        else:
            seen_mpns[key] = [comp.source_ref]
            unique_components.append(comp)

    lookup = PartsLookup()
    index: dict = {}
    ic_thermal: dict = {}
    passives_specs: dict = {}
    si_params: dict = {}
    warnings: list[str] = []
    downloaded = 0
    failed = 0
    skipped = 0
    specs_count = 0

    for comp in unique_components:
        mpn = comp.mpn or comp.lcsc_pn or ""
        if not mpn:
            continue
        refs = seen_mpns.get(mpn, [comp.source_ref])
        comp_type = _classify_component(comp)
        lookup_data = lookup.lookup(mpn)
        if delay > 0:
            time.sleep(delay)
        datasheet_url = (lookup_data or {}).get("datasheet_url", "") or ""

        index_entry: dict = {
            "mpn": mpn,
            "references": sorted(refs),
            "manufacturer": (lookup_data or {}).get("manufacturer", comp.source_manufacturer or ""),
            "description": (lookup_data or {}).get("description", comp.description or ""),
            "datasheet_url": datasheet_url,
            "type": comp_type,
            "status": "pending",
        }

        if not skip_download and datasheet_url:
            safe_name = re.sub(r"[^\w\-.]", "_", mpn)
            pdf_path = datasheets_dir / f"{safe_name}.pdf"
            if pdf_path.exists():
                index_entry.update(file=pdf_path.name, status="ok", size_bytes=pdf_path.stat().st_size)
                skipped += 1
            elif _download_datasheet(datasheet_url, pdf_path):
                index_entry.update(file=pdf_path.name, status="ok", size_bytes=pdf_path.stat().st_size)
                downloaded += 1
            else:
                index_entry.update(status="download_failed", error=f"Failed to download from {datasheet_url}")
                failed += 1
                warnings.append(f"Datasheet download failed for {mpn}: {datasheet_url}")
        elif skip_download:
            index_entry["status"] = "skipped"
            skipped += 1
        else:
            index_entry["status"] = "no_url"

        index[mpn] = index_entry

        if comp_type == "passive":
            pspec = _extract_passive_specs(comp, lookup_data)
            if pspec:
                passives_specs[f"{comp.value or mpn}_{comp.footprint or 'unknown'}"] = pspec
                specs_count += 1
        elif comp_type in ("ic", "semiconductor"):
            ispec = _extract_ic_specs(comp, lookup_data)
            if ispec:
                ic_thermal[mpn] = ispec
                specs_count += 1
                desc = (comp.description or "").lower()
                if any(w in desc for w in ("usb", "ddr", "lvds", "pcie", "mipi", "ethernet")):
                    si_params[mpn] = {"type": ispec.get("type", "ic"), "requires_impedance_control": True}

    datasheets_dir.mkdir(parents=True, exist_ok=True)
    specs_dir.mkdir(parents=True, exist_ok=True)

    index_data = {"project": project_name, "last_sync": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "parts": index}
    (datasheets_dir / "index.json").write_text(json.dumps(index_data, indent=2, ensure_ascii=False), encoding="utf-8")
    if ic_thermal:
        (specs_dir / "ic_thermal.json").write_text(
            json.dumps(ic_thermal, indent=2, ensure_ascii=False), encoding="utf-8"
        )
    if passives_specs:
        (specs_dir / "passives.json").write_text(
            json.dumps(passives_specs, indent=2, ensure_ascii=False), encoding="utf-8"
        )
    if si_params:
        (specs_dir / "si_params.json").write_text(json.dumps(si_params, indent=2, ensure_ascii=False), encoding="utf-8")

    return {
        "status": "ok",
        "project": project_name,
        "datasheets_dir": str(datasheets_dir),
        "specs_dir": str(specs_dir),
        "components_processed": len(unique_components),
        "datasheets_downloaded": downloaded,
        "datasheets_failed": failed,
        "datasheets_skipped": skipped,
        "specs_extracted": specs_count,
        "index": index_data,
        "warnings": warnings,
    }
