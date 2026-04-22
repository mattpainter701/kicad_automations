#!/usr/bin/env python3
"""Sync a local datasheets directory for a KiCad project via LCSC/jlcsearch.

Extracts components with MPNs or LCSC codes from a KiCad schematic (or
pre-computed analyzer JSON), searches jlcsearch for datasheet URLs,
downloads missing PDFs, and maintains an index.json manifest.

The index.json format matches across distributor skills so they can
contribute to the same datasheets directory. The source field
distinguishes which distributor provided the datasheet.

No API key required — uses the jlcsearch community API (free, no auth).
LCSC's CDN (wmsc.lcsc.com) serves PDFs directly without bot protection.

Download strategy per part:
  1. Try the datasheet URL from the schematic itself
  2. Search jlcsearch API → download from LCSC CDN (direct PDF URL)
  3. Try manufacturer-specific alternative URL patterns

Usage:
    python3 sync_datasheets_lcsc.py <file.kicad_sch>
    python3 sync_datasheets_lcsc.py <analyzer_output.json> --output ./datasheets
    python3 sync_datasheets_lcsc.py <file.kicad_sch> --force     # retry failures
    python3 sync_datasheets_lcsc.py <file.kicad_sch> --dry-run   # preview only

Dependencies:
    - requests (pip install requests) — strongly recommended
    - playwright (pip install playwright && playwright install chromium) — optional
"""

import argparse
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# Import from sibling script (same skill)
sys.path.insert(0, str(Path(__file__).parent))
from fetch_datasheet_lcsc import (
    download_pdf,
    normalize_url,
    try_alternative_sources,
    verify_datasheet,
    search_lcsc,
    _get_datasheet_url,
    _get_mpn,
    _get_lcsc_code,
    _get_manufacturer,
    _get_description,
)


# ---------------------------------------------------------------------------
# MPN filtering — distinguish real manufacturer part numbers from generic values
# ---------------------------------------------------------------------------

_GENERIC_VALUE_RE = re.compile(
    r"^[\d.]+\s*[pnuμmkMGR]?[FHΩRfhω]?$"
    r"|^[\d.]+\s*[kKmM]?[Ωω]?$"
    r"|^[\d.]+\s*[pnuμm]?[Ff]$"
    r"|^[\d.]+\s*[pnuμm]?[Hh]$"
    r"|^[\d.]+%$"
    r"|^DNP$|^NC$|^N/?A$",
    re.IGNORECASE,
)

_SKIP_TYPES = {
    "test_point", "mounting_hole", "fiducial", "graphic",
    "jumper", "net_tie", "mechanical",
}


def is_real_mpn(mpn: str) -> bool:
    """Return True if the string looks like a real manufacturer part number."""
    mpn = mpn.strip()
    if not mpn or len(mpn) < 3:
        return False
    if _GENERIC_VALUE_RE.match(mpn):
        return False
    has_letter = any(c.isalpha() for c in mpn)
    has_digit = any(c.isdigit() for c in mpn)
    return has_letter and has_digit


# ---------------------------------------------------------------------------
# Filename sanitization — matches convention across distributor skills
# ---------------------------------------------------------------------------

def sanitize_filename(name: str) -> str:
    """Convert a string to a safe filename component (without extension)."""
    name = re.sub(r'[/\\:*?"<>|,;]', "_", name)
    name = re.sub(r"\s+", "_", name)
    name = re.sub(r"_+", "_", name).strip("_")
    if len(name) > 200:
        name = name[:200]
    return name


def friendly_filename(mpn: str, description: str = "", manufacturer: str = "") -> str:
    """Build a human-readable filename from MPN and description."""
    base = sanitize_filename(mpn)
    if not description:
        return base
    desc = description.strip()
    if manufacturer and desc.lower().endswith(manufacturer.lower()):
        desc = desc[: -len(manufacturer)].strip().rstrip(",").strip()
    if len(desc) > 80:
        desc = desc[:77].rsplit("_", 1)[0].rsplit(" ", 1)[0]
    desc = sanitize_filename(desc)
    return f"{base}_{desc}" if desc else base


# ---------------------------------------------------------------------------
# Manifest (index.json) management
# ---------------------------------------------------------------------------

def load_index(path: Path) -> dict:
    """Load existing index.json or return empty structure."""
    if path.exists():
        try:
            with open(path, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return {"schematic": "", "last_sync": "", "parts": {}}


def save_index(path: Path, index: dict):
    """Write index.json atomically."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w") as f:
        json.dump(index, f, indent=2)
    tmp.rename(path)


# ---------------------------------------------------------------------------
# Schematic analysis — run analyzer or load pre-computed JSON
# ---------------------------------------------------------------------------

def get_analyzer_output(input_path: Path) -> dict | None:
    """Get analyzer output, either by running the analyzer or loading JSON."""
    if input_path.suffix == ".json":
        with open(input_path, "r") as f:
            return json.load(f)

    if input_path.suffix in (".kicad_sch", ".sch"):
        kicad_scripts = Path(__file__).resolve().parent.parent.parent / "kicad" / "scripts"
        if kicad_scripts.exists():
            sys.path.insert(0, str(kicad_scripts))
            try:
                from analyze_schematic import analyze_schematic
                return analyze_schematic(str(input_path))
            except Exception as e:
                print(f"  Analyzer import failed ({e}), trying subprocess...",
                      file=sys.stderr)

        analyzer = kicad_scripts / "analyze_schematic.py"
        if not analyzer.exists():
            print(f"Error: Cannot find analyze_schematic.py at {analyzer}",
                  file=sys.stderr)
            return None
        try:
            result = subprocess.run(
                [sys.executable, str(analyzer), str(input_path), "--compact"],
                capture_output=True, text=True, timeout=120,
            )
            if result.returncode != 0:
                print(f"Error: Analyzer failed: {result.stderr[:500]}",
                      file=sys.stderr)
                return None
            return json.loads(result.stdout)
        except Exception as e:
            print(f"Error: Failed to run analyzer: {e}", file=sys.stderr)
            return None

    print(f"Error: Unsupported input file type: {input_path.suffix}",
          file=sys.stderr)
    return None


# ---------------------------------------------------------------------------
# Part extraction from BOM
# ---------------------------------------------------------------------------

def extract_parts(analyzer_output: dict) -> list[dict]:
    """Extract unique parts with MPNs or distributor PNs from analyzer BOM.

    A part is included if it has at least one of: a real MPN, an LCSC code,
    a DigiKey PN, or a Mouser PN. Users set up KiCad projects differently.
    """
    bom = analyzer_output.get("bom", [])
    parts = []

    for entry in bom:
        if entry.get("dnp"):
            continue
        if entry.get("type", "") in _SKIP_TYPES:
            continue

        mpn = entry.get("mpn", "").strip()
        lcsc_pn = entry.get("lcsc", "").strip()
        digikey_pn = entry.get("digikey", "").strip()
        mouser_pn = entry.get("mouser", "").strip()

        has_mpn = is_real_mpn(mpn)
        has_distributor_pn = bool(lcsc_pn or digikey_pn or mouser_pn)
        if not has_mpn and not has_distributor_pn:
            continue

        parts.append({
            "mpn": mpn if has_mpn else "",
            "manufacturer": entry.get("manufacturer", ""),
            "value": entry.get("value", ""),
            "description": entry.get("description", ""),
            "datasheet": entry.get("datasheet", ""),
            "references": entry.get("references", []),
            "type": entry.get("type", ""),
            "lcsc": lcsc_pn,
            "digikey": digikey_pn,
            "mouser": mouser_pn,
        })

    return parts


# ---------------------------------------------------------------------------
# Core sync logic
# ---------------------------------------------------------------------------

def sync_one_part(
    part: dict,
    output_dir: Path,
    index: dict,
    delay: float,
) -> dict:
    """Download datasheet for one part. Returns updated manifest entry."""
    mpn = part["mpn"]
    lcsc_pn = part.get("lcsc", "")
    now = datetime.now(timezone.utc).isoformat()

    # Use MPN for display/filename if available, otherwise LCSC code
    display_pn = mpn or lcsc_pn

    desc = part.get("description", "")
    mfg = part.get("manufacturer", "")
    filename = friendly_filename(display_pn, desc, mfg) + ".pdf"
    output_path = output_dir / filename

    # Strategy 1: Try the datasheet URL from the schematic itself
    schematic_url = part.get("datasheet", "")
    if schematic_url and schematic_url != "~" and "://" in schematic_url:
        print(f"  Trying schematic URL...", file=sys.stderr)
        if download_pdf(schematic_url, str(output_path)):
            size = os.path.getsize(str(output_path))
            vr = verify_datasheet(str(output_path), display_pn, desc, mfg)
            if vr["confidence"] == "wrong":
                print(f"  WARNING: PDF may be wrong datasheet — {vr['details']}",
                      file=sys.stderr)
            result = {
                "file": filename,
                "manufacturer": mfg,
                "description": desc,
                "value": part["value"],
                "datasheet_url": schematic_url,
                "downloaded_date": now,
                "source": "schematic",
                "status": "ok",
                "references": part["references"],
                "size_bytes": size,
                "verification": vr["confidence"],
            }
            if vr["confidence"] == "wrong":
                result["verification_details"] = vr["details"]
            return result

    # Strategy 2: Search jlcsearch API
    # Prefer LCSC code (exact match) over MPN keyword search
    search_term = lcsc_pn or mpn
    time.sleep(delay)
    print(f"  Searching LCSC for '{search_term}'...", file=sys.stderr)
    component = search_lcsc(search_term)

    # If LCSC code search failed but we have an MPN, try that
    if component is None and lcsc_pn and mpn:
        time.sleep(delay)
        print(f"  LCSC code not found, trying MPN '{mpn}'...", file=sys.stderr)
        component = search_lcsc(mpn)

    if component is not None:
        ds_url = _get_datasheet_url(component)
        lcsc_mpn = _get_mpn(component)
        lcsc_mfg = _get_manufacturer(component) or mfg
        lcsc_desc = _get_description(component) or desc
        lcsc_code = _get_lcsc_code(component)

        # Use the richer LCSC data for filename
        effective_pn = lcsc_mpn or display_pn
        if lcsc_desc:
            filename = friendly_filename(effective_pn, lcsc_desc, lcsc_mfg) + ".pdf"
            output_path = output_dir / filename

        if ds_url:
            print(f"  Downloading from LCSC CDN...", file=sys.stderr)
            if download_pdf(ds_url, str(output_path)):
                size = os.path.getsize(str(output_path))
                vr = verify_datasheet(str(output_path), effective_pn, lcsc_desc, lcsc_mfg)
                if vr["confidence"] == "wrong":
                    print(f"  WARNING: PDF may be wrong datasheet — {vr['details']}",
                          file=sys.stderr)
                result = {
                    "file": filename,
                    "manufacturer": lcsc_mfg,
                    "description": lcsc_desc,
                    "value": part["value"],
                    "datasheet_url": ds_url,
                    "downloaded_date": now,
                    "source": "lcsc",
                    "lcsc": lcsc_code,
                    "status": "ok",
                    "references": part["references"],
                    "size_bytes": size,
                    "verification": vr["confidence"],
                }
                if vr["confidence"] == "wrong":
                    result["verification_details"] = vr["details"]
                return result

    # Strategy 3: Try alternative manufacturer sources
    if mpn:
        print(f"  Trying alternative sources...", file=sys.stderr)
        if try_alternative_sources(mpn, str(output_path)):
            size = os.path.getsize(str(output_path))
            vr = verify_datasheet(str(output_path), mpn, desc, mfg)
            result = {
                "file": filename,
                "manufacturer": mfg,
                "description": desc,
                "value": part["value"],
                "datasheet_url": "",
                "downloaded_date": now,
                "source": "alternative",
                "status": "ok",
                "references": part["references"],
                "size_bytes": size,
                "verification": vr["confidence"],
            }
            if vr["confidence"] == "wrong":
                result["verification_details"] = vr["details"]
            return result

    if component is None:
        return {
            "manufacturer": mfg,
            "description": desc,
            "value": part["value"],
            "references": part["references"],
            "status": "not_found",
            "error": f"No LCSC results for '{search_term}'" + (f" or '{mpn}'" if lcsc_pn and mpn else ""),
            "last_attempt": now,
        }

    return {
        "manufacturer": mfg,
        "description": desc,
        "value": part["value"],
        "references": part["references"],
        "status": "failed",
        "error": "No datasheet URL or all download methods failed",
        "last_attempt": now,
    }


def sync_datasheets(
    input_path: str,
    output_dir: str | None = None,
    force: bool = False,
    force_all: bool = False,
    delay: float = 0.5,
    dry_run: bool = False,
    as_json: bool = False,
) -> dict:
    """Main sync function. Returns summary dict."""
    input_path = Path(input_path).resolve()

    if output_dir:
        out_dir = Path(output_dir)
    else:
        out_dir = input_path.parent / "datasheets"
    out_dir.mkdir(parents=True, exist_ok=True)

    index_path = out_dir / "index.json"
    index = load_index(index_path)

    print(f"Analyzing {input_path.name}...", file=sys.stderr)
    analyzer_output = get_analyzer_output(input_path)
    if analyzer_output is None:
        return {"error": "Failed to analyze schematic"}

    parts = extract_parts(analyzer_output)
    all_bom = analyzer_output.get("bom", [])
    skipped_no_id = sum(
        1 for e in all_bom
        if not e.get("dnp") and e.get("type", "") not in _SKIP_TYPES
        and not is_real_mpn(e.get("mpn", ""))
        and not e.get("lcsc", "").strip()
        and not e.get("digikey", "").strip()
        and not e.get("mouser", "").strip()
    )

    print(f"Found {len(parts)} unique parts with identifiers "
          f"({skipped_no_id} skipped without any identifier)", file=sys.stderr)

    to_download = []
    already_present = []
    skipped_failed = []

    for part in parts:
        part_key = part["mpn"] or part.get("lcsc", "") or part.get("digikey", "") or part.get("mouser", "")
        part["_key"] = part_key
        existing = index.get("parts", {}).get(part_key, {})
        status = existing.get("status", "")

        if status == "ok":
            old_file = existing.get("file", "")
            if (out_dir / old_file).exists():
                if not force_all:
                    already_present.append(part_key)
                    existing["references"] = part["references"]
                    continue

        if status in ("failed", "not_found", "no_datasheet") and not (force or force_all):
            skipped_failed.append(part_key)
            continue

        to_download.append(part)

    if dry_run:
        summary = {
            "would_download": [p["_key"] for p in to_download],
            "already_present": already_present,
            "skipped_previous_failures": skipped_failed,
            "skipped_no_identifier": skipped_no_id,
        }
        if as_json:
            json.dump(summary, sys.stdout, indent=2)
        else:
            print(f"\nDry run — would download {len(to_download)} datasheets:")
            for p in to_download:
                print(f"  {p['_key']} ({p['manufacturer'] or 'unknown mfg'})")
            print(f"Already present: {len(already_present)}")
            print(f"Skipped (previous failures): {len(skipped_failed)}")
            print(f"Skipped (no identifier): {skipped_no_id}")
        return summary

    if not to_download:
        msg = f"All {len(already_present)} datasheets up to date."
        if skipped_failed:
            msg += f" {len(skipped_failed)} previous failures (use --force to retry)."
        print(msg, file=sys.stderr)
        index["schematic"] = str(input_path)
        index["last_sync"] = datetime.now(timezone.utc).isoformat()
        save_index(index_path, index)
        return {"downloaded": 0, "already_present": len(already_present),
                "failed": len(skipped_failed)}

    downloaded = []
    failed = []
    warnings = []

    for i, part in enumerate(to_download):
        part_key = part["_key"]
        print(f"[{i+1}/{len(to_download)}] {part_key}", file=sys.stderr)

        result = sync_one_part(part, out_dir, index, delay)

        index.setdefault("parts", {})[part_key] = result

        if result["status"] == "ok":
            downloaded.append(part_key)
            vconf = result.get("verification", "")
            vmark = ""
            if vconf == "wrong":
                vmark = " ⚠ WRONG DATASHEET?"
                warnings.append(part_key)
            elif vconf == "unverified":
                vmark = " (unverified)"
            print(f"  OK: {result['file']} ({result['size_bytes']:,} bytes){vmark}",
                  file=sys.stderr)
        else:
            failed.append(part_key)
            print(f"  {result['status'].upper()}: {result.get('error', '')}",
                  file=sys.stderr)

        # Save after each download so progress is preserved on interrupt
        index["schematic"] = str(input_path)
        index["last_sync"] = datetime.now(timezone.utc).isoformat()
        save_index(index_path, index)

    summary = {
        "downloaded": len(downloaded),
        "already_present": len(already_present),
        "failed": len(failed),
        "verification_warnings": len(warnings),
        "skipped_previous_failures": len(skipped_failed),
        "skipped_no_identifier": skipped_no_id,
        "total_identified_parts": len(parts),
        "output_dir": str(out_dir),
        "index_path": str(index_path),
    }

    if as_json:
        json.dump(summary, sys.stdout, indent=2)
    else:
        print(f"\nDatasheet sync complete:", file=sys.stderr)
        print(f"  Downloaded: {len(downloaded)}", file=sys.stderr)
        if downloaded:
            for m in downloaded:
                print(f"    {m}", file=sys.stderr)
        if warnings:
            print(f"  Verification warnings: {len(warnings)}", file=sys.stderr)
            for m in warnings:
                entry = index["parts"].get(m, {})
                detail = entry.get("verification_details", "")
                print(f"    {m}: {detail}", file=sys.stderr)
        print(f"  Already present: {len(already_present)}", file=sys.stderr)
        print(f"  Failed: {len(failed)}", file=sys.stderr)
        if failed:
            for m in failed:
                entry = index["parts"].get(m, {})
                err = entry.get("error", "")
                print(f"    {m} — {err}", file=sys.stderr)
        if skipped_failed:
            print(f"  Skipped (previous failures, use --force): "
                  f"{len(skipped_failed)}", file=sys.stderr)
        print(f"  Skipped (no identifier): {skipped_no_id}", file=sys.stderr)
        print(f"  Output: {out_dir}/", file=sys.stderr)

    return summary


def main():
    parser = argparse.ArgumentParser(
        description="Sync datasheets for a KiCad project via LCSC/jlcsearch (no API key needed)",
    )
    parser.add_argument(
        "input",
        help="Path to .kicad_sch file or pre-computed analyzer JSON",
    )
    parser.add_argument(
        "--output", "-o",
        help="Output directory (default: datasheets/ next to input file)",
    )
    parser.add_argument(
        "--force", action="store_true",
        help="Retry previously failed downloads",
    )
    parser.add_argument(
        "--force-all", action="store_true",
        help="Re-download everything, including already-present files",
    )
    parser.add_argument(
        "--delay", type=float, default=0.5,
        help="Seconds between API calls (default: 0.5)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Show what would be downloaded without doing it",
    )
    parser.add_argument(
        "--json", action="store_true",
        help="Output summary as JSON",
    )
    args = parser.parse_args()

    result = sync_datasheets(
        input_path=args.input,
        output_dir=args.output,
        force=args.force,
        force_all=args.force_all,
        delay=args.delay,
        dry_run=args.dry_run,
        as_json=args.json,
    )

    if "error" in result:
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
