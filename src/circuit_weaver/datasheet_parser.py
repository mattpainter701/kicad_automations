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
