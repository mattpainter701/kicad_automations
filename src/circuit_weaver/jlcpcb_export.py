"""JLCPCB BOM and CPL export for assembly ordering.

Generates:
- BOM CSV (Comment, Designator, Footprint, LCSC Part#)
- CPL CSV (Designator, Mid X, Mid Y, Rotation, Layer)
- README_jlcpcb.txt with upload instructions

Usage:
    from circuit_weaver.jlcpcb_export import export_jlcpcb
    result = export_jlcpcb(spec, output_dir="/tmp/jlcpcb_export")
"""

from __future__ import annotations

import csv
import os
import re
import shutil
import time
import uuid
from contextlib import ExitStack, contextmanager
from pathlib import Path
from typing import Any, Iterable, Mapping

from .assembly_manifest import (
    AssemblyItem,
    AssemblyManifest,
    build_assembly_manifest,
    coerce_assembly_manifest,
)
from .component_db import ComponentDef
from .delivery_manifest import DeliveryArtifact, DeliveryManifest


class CplSourceError(ValueError):
    """Raised when a PCB cannot truthfully serve as an assembly CPL source."""


_DELIVERY_LOCK_FILE = ".circuit-weaver-jlcpcb.lock"


@contextmanager
def _delivery_output_lock(directory: Path, *, timeout: float = 30.0):
    """Serialize one complete delivery transaction across processes.

    The persistent lock file avoids an unlink/recreate inode race.  File-region
    locking is available in the Python standard library on both Windows and
    POSIX, so the manufacturing path does not gain a runtime dependency.
    """
    directory.mkdir(parents=True, exist_ok=True)
    lock_path = directory / _DELIVERY_LOCK_FILE
    deadline = time.monotonic() + timeout
    with lock_path.open("a+b") as handle:
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"\0")
            handle.flush()

        acquired = False
        while not acquired:
            try:
                handle.seek(0)
                if os.name == "nt":
                    import msvcrt

                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
            except OSError as exc:
                if time.monotonic() >= deadline:
                    raise TimeoutError(f"Timed out waiting for JLCPCB delivery lock: {lock_path}") from exc
                time.sleep(0.05)

        try:
            yield
        finally:
            handle.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _owned_delivery_files(directory: Path) -> list[Path]:
    exact = {
        "assembly_manifest.json",
        "delivery_manifest.json",
        "bom_jlcpcb.csv",
        "cpl_jlcpcb.csv",
        "README_jlcpcb.txt",
    }
    return [
        path
        for path in directory.iterdir()
        if path.is_file() and (path.name in exact or re.fullmatch(r"(?:bom|cpl)_jlcpcb_.+\.csv", path.name) is not None)
    ]


def _remove_owned_delivery_files(directory: Path) -> None:
    if not directory.is_dir():
        return
    for path in _owned_delivery_files(directory):
        path.unlink(missing_ok=True)


def _publish_delivery_staging(
    staging: Path,
    destination: Path,
    *,
    _lock_held: bool = False,
) -> None:
    """Publish a complete delivery set, with the manifest as commit marker.

    Existing owned files are first hidden in a private backup directory.  The
    staged delivery manifest is moved last, so a process that watches this
    directory cannot mistake a partly published set for a committed delivery.
    If any move fails, both the previous delivery and every partial new file
    are removed: an error must never leave an older CPL looking current.
    """
    if not _lock_held:
        with _delivery_output_lock(destination):
            _publish_delivery_staging(staging, destination, _lock_held=True)
        return

    staged = [path for path in staging.iterdir() if path.is_file()]
    staged.sort(key=lambda path: (path.name == "delivery_manifest.json", path.name))
    backup = destination / f".cw-jlc-backup-{uuid.uuid4().hex}"
    backup.mkdir()
    try:
        previous_files = _owned_delivery_files(destination)
        previous_files.sort(key=lambda path: (path.name != "delivery_manifest.json", path.name))
        for previous in previous_files:
            os.replace(previous, backup / previous.name)
        for source in staged:
            os.replace(source, destination / source.name)
    except Exception:
        _remove_owned_delivery_files(destination)
        raise
    finally:
        shutil.rmtree(backup, ignore_errors=True)
        shutil.rmtree(staging, ignore_errors=True)


def _extract_sexpr_blocks(text: str, keyword: str) -> list[str]:
    """Extract balanced S-expression blocks while respecting quoted strings."""
    starts = list(re.finditer(rf"\({re.escape(keyword)}(?=\s|\))", text))
    blocks: list[str] = []
    for match in starts:
        depth = 0
        in_string = False
        escaped = False
        for idx in range(match.start(), len(text)):
            char = text[idx]
            if in_string:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == '"':
                    in_string = False
                continue
            if char == '"':
                in_string = True
            elif char == "(":
                depth += 1
            elif char == ")":
                depth -= 1
                if depth == 0:
                    blocks.append(text[match.start() : idx + 1])
                    break
    return blocks


def _pcb_layer_to_cpl(layer: str) -> str:
    normalized = (layer or "").strip().lower()
    if normalized in {"top", "front", "f.cu"}:
        return "top"
    if normalized in {"bottom", "back", "b.cu"}:
        return "bottom"
    raise CplSourceError(f"Unsupported PCB footprint layer for CPL: {layer or '(missing)'}")


def _footprint_identity(block: str) -> str:
    match = re.match(r'^\(footprint\s+"((?:\\.|[^"\\])*)"', block)
    if match is None:
        return ""
    return match.group(1).replace(r"\"", '"').replace(r"\\", "\\").strip()


def _normalized_footprint_identity(value: str) -> str:
    return (value or "").strip().replace("\\", "/").casefold()


def parse_pcb_placements(
    pcb_path: str | Path,
    *,
    required_refs: set[str] | None = None,
    expected_footprints: dict[str, str] | None = None,
) -> dict[str, tuple[float, float, float, str]]:
    """Parse placements from a real, pad-bearing KiCad PCB.

    Placement-preview boards are rejected explicitly.  A board with no pads is
    also rejected, preventing synthetic footprint shells from becoming an
    upload-ready CPL.  When ``required_refs`` is supplied, every requested
    reference must resolve to a pad-bearing footprint.  ``expected_footprints``
    additionally binds each reference to the assembly manifest's physical
    package, preventing a stale PCB with coincidentally matching references
    from becoming an apparently ready CPL.
    """
    path = Path(pcb_path)
    if not path.is_file():
        raise CplSourceError(f"Physical PCB not found: {path}")
    text = path.read_text(encoding="utf-8")
    lowered = text.lower()
    if "placement_preview" in lowered or "placement_preview:missing_" in lowered:
        raise CplSourceError("Placement preview cannot be used as an upload-ready CPL source")

    origin_x = 0.0
    origin_y = 0.0
    origin_match = re.search(r"\(aux_axis_origin\s+([-+\d.eE]+)\s+([-+\d.eE]+)\)", text)
    if origin_match:
        origin_x = float(origin_match.group(1))
        origin_y = float(origin_match.group(2))

    placements: dict[str, tuple[float, float, float, str]] = {}
    pad_bearing_count = 0
    for block in _extract_sexpr_blocks(text, "footprint"):
        reference_match = re.search(r'\(property\s+"Reference"\s+"([^"]+)"', block)
        if reference_match is None:
            reference_match = re.search(r'\(fp_text\s+reference\s+"([^"]+)"', block)
        if reference_match is None:
            continue
        reference = reference_match.group(1).strip()
        if not reference or reference.startswith("REF**"):
            continue
        if not re.search(r"\(pad(?=\s|\))", block):
            continue
        pad_bearing_count += 1

        at_match = re.search(
            r"\(at\s+([-+\d.eE]+)\s+([-+\d.eE]+)(?:\s+([-+\d.eE]+))?\)",
            block,
        )
        layer_match = re.search(r'\(layer\s+"([^"]+)"\)', block)
        if at_match is None or layer_match is None:
            raise CplSourceError(f"Pad-bearing footprint {reference} lacks placement or layer data")
        if reference in placements:
            raise CplSourceError(f"Duplicate PCB footprint reference: {reference}")

        if expected_footprints is not None and reference in expected_footprints:
            expected = expected_footprints[reference]
            actual = _footprint_identity(block)
            if not actual:
                raise CplSourceError(f"Pad-bearing footprint {reference} lacks a footprint identity")
            if _normalized_footprint_identity(actual) != _normalized_footprint_identity(expected):
                raise CplSourceError(
                    f"PCB footprint identity mismatch for {reference}: "
                    f"assembly expects {expected!r}, board contains {actual!r}"
                )

        x = float(at_match.group(1)) - origin_x
        y = float(at_match.group(2)) - origin_y
        rotation = float(at_match.group(3) or 0.0) % 360.0
        placements[reference] = (x, y, rotation, _pcb_layer_to_cpl(layer_match.group(1)))

    if pad_bearing_count == 0:
        raise CplSourceError("PCB contains no pad-bearing footprints; CPL generation is blocked")

    if required_refs is not None:
        if not required_refs:
            raise CplSourceError("Assembly manifest has no active placement references")
        missing = sorted(required_refs - set(placements))
        if missing:
            preview = ", ".join(missing[:12])
            suffix = f" and {len(missing) - 12} more" if len(missing) > 12 else ""
            raise CplSourceError(f"PCB is missing pad-bearing assembly refs: {preview}{suffix}")
        allowed_extra = re.compile(r"^(?:FID|MH|H)\d+$", re.IGNORECASE)
        unexpected = sorted(
            reference for reference in set(placements) - required_refs if not allowed_extra.fullmatch(reference)
        )
        if unexpected:
            preview = ", ".join(unexpected[:12])
            suffix = f" and {len(unexpected) - 12} more" if len(unexpected) > 12 else ""
            raise CplSourceError(f"PCB contains unexpected pad-bearing assembly refs: {preview}{suffix}")

    return placements


def group_bom_rows(
    components: AssemblyManifest | list[AssemblyItem] | list[ComponentDef],
) -> list[dict[str, Any]]:
    """Group components into BOM rows by (value, footprint, lcsc_pn).

    Returns list of dicts:
        {
            "comment": str,          # value or MPN
            "designators": str,      # comma-separated sorted refs
            "footprint": str,        # last segment after ':'
            "lcsc_pn": str,          # LCSC part number or empty
            "has_lcsc": bool,        # whether LCSC number is present
        }
    """
    manifest = coerce_assembly_manifest(components)

    # Group by (value, footprint, lcsc_pn)
    groups: dict[tuple, list[str]] = {}

    for item in manifest.active_bom_items():
        # Extract footprint last segment (e.g., "SOT-23-6" from "Package_TO_SOT_SMD:SOT-23-6")
        footprint = item.footprint
        if ":" in footprint:
            footprint = footprint.split(":")[-1]

        # LCSC is an exact purchasable identity. Without it, preserve MPN and
        # manufacturer in the grouping key so two incompatible parts that
        # happen to share a display value/footprint never collapse together.
        comment = item.value or item.mpn
        lcsc_pn = item.lcsc_pn or ""
        identity_mpn = "" if lcsc_pn else item.mpn
        identity_manufacturer = "" if lcsc_pn else item.manufacturer
        key = (comment, footprint, lcsc_pn, identity_mpn, identity_manufacturer)

        if key not in groups:
            groups[key] = []
        groups[key].append(item.reference)

    # Build rows
    rows = []
    for (comment, footprint, lcsc_pn, _mpn, _manufacturer), refs in sorted(groups.items()):
        rows.append(
            {
                "comment": comment,
                "designators": ",".join(sorted(refs)),
                "footprint": footprint,
                "lcsc_pn": lcsc_pn,
                "has_lcsc": bool(lcsc_pn),
            }
        )

    return rows


def write_jlcpcb_bom(bom_rows: list[dict], output_path: Path) -> None:
    """Write JLCPCB BOM CSV.

    Columns: Comment, Designator, Footprint, LCSC Part#
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["Comment", "Designator", "Footprint", "LCSC Part#"])
        for row in bom_rows:
            writer.writerow(
                [
                    row["comment"],
                    row["designators"],
                    row["footprint"],
                    row["lcsc_pn"] if row["has_lcsc"] else "",
                ]
            )


def _assembly_reference(item: AssemblyItem | ComponentDef) -> str:
    if isinstance(item, AssemblyItem):
        return item.reference
    return item.source_ref or ""


def write_jlcpcb_cpl(
    components: list[AssemblyItem] | list[ComponentDef],
    placements: dict[str, tuple[float, float, float, str]],
    output_path: Path,
) -> None:
    """Write JLCPCB CPL (centroid/placement) CSV.

    Columns: Designator, Mid X, Mid Y, Rotation, Layer
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["Designator", "Mid X", "Mid Y", "Rotation", "Layer"])
        for item in components:
            reference = _assembly_reference(item)
            if not reference or reference not in placements:
                continue
            x, y, rotation, layer = placements[reference]
            writer.writerow([reference, f"{x:.2f}", f"{y:.2f}", f"{rotation:.1f}", _pcb_layer_to_cpl(layer)])


def write_dual_sided_cpl(
    components: list[ComponentDef],
    placements: dict[str, tuple[float, float, float, str]],
    output_dir: Path,
    *,
    assembly_mode: str = "dual-sided-sequential",
) -> dict:
    """Write separate top/bottom CPL files for dual-sided assembly."""
    top_lines = ["Designator,Mid X,Mid Y,Rotation,Layer"]
    bottom_lines = ["Designator,Mid X,Mid Y,Rotation,Layer"]
    warnings: list[str] = []
    bottom_refs: list[str] = []

    for comp in components:
        ref = comp.source_ref or ""
        if not ref or ref not in placements:
            continue
        x, y, rotation, layer = placements[ref]
        jlcpcb_layer = "top" if layer in ("top", "front", "F.Cu") else "bottom"
        line = f"{ref},{x:.2f},{y:.2f},{rotation:.1f},{jlcpcb_layer}"
        if jlcpcb_layer == "top":
            top_lines.append(line)
        else:
            bottom_lines.append(line)
            bottom_refs.append(ref)

    for comp in components:
        ref = comp.source_ref or ""
        if ref not in bottom_refs:
            continue
        fp = (comp.footprint or "").upper()
        if any(kw in fp for kw in ("THT", "CONN", "USB", "BARREL", "HEADER")):
            warnings.append(f"{ref}: tall/THT component on bottom side — may interfere with stacking")
        if any(kw in fp for kw in ("QFN", "BGA", "DFN")):
            warnings.append(f"{ref}: {fp} on bottom side — ensure thermal pad vias exist (solder wicking risk)")

    if assembly_mode == "single-sided" and len(bottom_lines) > 1:
        warnings.append(f"{len(bottom_lines) - 1} components assigned to bottom but assembly mode is single-sided")
    if assembly_mode == "dual-sided-simultaneous":
        warnings.append(
            "Simultaneous reflow: verify thermal profile handles both sides. Heavy bottom components may fall."
        )

    output_dir.mkdir(parents=True, exist_ok=True)
    top_path = output_dir / "cpl_top.csv"
    bottom_path = output_dir / "cpl_bottom.csv"
    top_path.write_text("\n".join(top_lines) + "\n", encoding="utf-8")
    bottom_path.write_text("\n".join(bottom_lines) + "\n", encoding="utf-8")

    return {
        "top_file": str(top_path),
        "bottom_file": str(bottom_path),
        "top_count": len(top_lines) - 1,
        "bottom_count": len(bottom_lines) - 1,
        "assembly_mode": assembly_mode,
        "warnings": warnings,
    }


def _variant_file_token(name: str) -> str:
    """Return a filesystem-safe token for an assembly variant name."""
    token = "".join(ch.lower() if ch.isalnum() else "_" for ch in (name or "default"))
    token = "_".join(part for part in token.split("_") if part)
    return token or "default"


def generate_assembly_variants(
    components: AssemblyManifest | list[AssemblyItem] | list[ComponentDef],
    variants: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Generate component subsets for JLCPCB assembly variants.

    Variant specs are deliberately simple and data-oriented so they can be
    emitted by design YAML, a future CLI flag, or downstream ordering tools:

    ``{"name": "sensorless", "exclude_refs": ["U2"], "dnp_refs": ["R5"]}``

    ``include_refs`` is optional. If present, only those designators are
    considered. ``exclude_refs`` and ``dnp_refs`` then remove components from
    the assembly set. Generated support parts follow their owner component when
    an owner is included, excluded, or marked DNP.
    """
    manifest = coerce_assembly_manifest(components)
    specs = variants or [{"name": "default"}]
    by_ref = {item.reference: item for item in manifest.active_bom_items()}
    all_refs = set(by_ref)
    out: list[dict[str, Any]] = []
    used_tokens: dict[str, int] = {}

    for idx, spec in enumerate(specs):
        name = str(spec.get("name") or f"variant_{idx + 1}")
        base_token = _variant_file_token(name)
        token_count = used_tokens.get(base_token, 0) + 1
        used_tokens[base_token] = token_count
        token = base_token if token_count == 1 else f"{base_token}_{token_count}"
        include_refs = {str(ref) for ref in spec.get("include_refs", []) if str(ref)}
        exclude_refs = {str(ref) for ref in spec.get("exclude_refs", []) if str(ref)}
        dnp_refs = {str(ref) for ref in spec.get("dnp_refs", []) if str(ref)}

        if include_refs:
            unknown_include_refs = sorted(include_refs - all_refs)
            if unknown_include_refs:
                raise ValueError(
                    f"Assembly variant {name!r} includes unknown active reference(s): "
                    + ", ".join(unknown_include_refs)
                )
            candidate_refs = include_refs & all_refs
            candidate_refs |= {item.reference for item in by_ref.values() if item.owner_ref in include_refs}
        else:
            candidate_refs = set(all_refs)

        removed_owner_refs = exclude_refs | dnp_refs
        removed_refs = (exclude_refs | dnp_refs) & all_refs
        removed_refs |= {item.reference for item in by_ref.values() if item.owner_ref in removed_owner_refs}
        assembled_refs = sorted(candidate_refs - removed_refs)
        if include_refs and not assembled_refs:
            raise ValueError(f"Assembly variant {name!r} include_refs resolve to no active assembly items")
        assembled_components = [by_ref[ref] for ref in assembled_refs]
        omitted_refs = sorted(all_refs - set(assembled_refs))

        out.append(
            {
                "name": name,
                "token": token,
                "components": assembled_components,
                "bom_rows": group_bom_rows(assembled_components),
                "included_refs": assembled_refs,
                "omitted_refs": omitted_refs,
                "dnp_refs": sorted(dnp_refs),
            }
        )

    return out


def write_jlcpcb_readme(
    project_name: str,
    output_path: Path,
    *,
    cpl_included: bool = False,
    blocked_reasons: list[str] | None = None,
) -> None:
    """Write truthful upload instructions for the artifacts actually present."""
    lines = []
    lines.append("JLCPCB PCB Assembly Upload Instructions")
    lines.append("=" * 50)
    lines.append("")
    lines.append(f"Project: {project_name}")
    lines.append("")
    lines.append("Files Included:")
    lines.append("  - bom_jlcpcb.csv        BOM for parts matching")
    if cpl_included:
        lines.append("  - cpl_jlcpcb.csv        Centroid data parsed from the supplied physical PCB")
    else:
        lines.append("  - cpl_jlcpcb.csv        NOT GENERATED")
    lines.append("  - assembly_manifest.json Exhaustive primary + generated support-part inventory")
    lines.append("  - delivery_manifest.json Artifact readiness and blocking reasons")
    lines.append("  - (gerbers/)            Gerber files (export separately from KiCad)")
    lines.append("")
    if blocked_reasons:
        lines.append("Blocked / incomplete delivery reasons:")
        for reason in blocked_reasons:
            lines.append(f"  - {reason}")
        lines.append("")
    lines.append("Upload Steps:")
    lines.append("  1. Go to https://jlcpcb.com/quote")
    lines.append("  2. Upload Gerber ZIP file")
    lines.append("  3. Configure PCB: 2-layer, 1.6mm thickness, color, quantity")
    lines.append("  4. Proceed to quote")
    lines.append("  5. Enable 'PCB Assembly'")
    lines.append("  6. Upload BOM file (bom_jlcpcb.csv)")
    if cpl_included:
        lines.append("  7. Upload CPL file (cpl_jlcpcb.csv)")
    else:
        lines.append("  7. Generate CPL from a real, pad-bearing PCB before assembly upload")
    lines.append("  8. Review part matching and confirm")
    lines.append("")
    lines.append("Notes:")
    lines.append("  - Parts with empty LCSC Part# must be sourced separately")
    lines.append("  - JLCPCB basic parts (no setup fee): ~700 common components")
    lines.append("  - Extended parts (setup fee $3 each): remaining components")
    lines.append("  - Verify all part matches before confirming order")
    lines.append("")

    output_path.write_text("\n".join(lines), encoding="utf-8")


def _detect_price_breaks(bom_rows: list[dict]) -> list[dict]:
    """Query LCSC pricing for each BOM row and detect price breaks.

    For each row with an LCSC part number, attempts to fetch pricing at
    standard quantity tiers (1, 10, 100). Returns price-break alerts
    where ordering higher quantity reduces per-unit cost by > 20%.

    Returns list of alert dicts:
        {
            "designators": str,
            "lcsc_pn": str,
            "price_1": float,    # price at qty 1
            "price_10": float,   # price at qty 10 (or same as qty 1)
            "price_100": float,  # price at qty 100 (or same as qty 1)
            "savings_pct_100": float,  # savings % at qty 100 vs qty 1
        }
    """
    alerts: list[dict] = []

    for row in bom_rows:
        lcsc_pn = row.get("lcsc_pn", "")
        if not lcsc_pn:
            continue

        try:
            from .parts_lookup import PartsLookup

            lookup = PartsLookup()
            result = lookup.lookup_by_lcsc(lcsc_pn)
            if not result:
                continue

            # Extract pricing from LCSC result
            prices = result.get("prices", {}) or {}
            price_1 = _parse_price(prices.get("1", prices.get("qty_1", "")))
            price_10 = _parse_price(prices.get("10", prices.get("qty_10", "")))
            price_100 = _parse_price(prices.get("100", prices.get("qty_100", "")))

            # Fall back to price field if-tiered data unavailable
            single_price = result.get("price", 0)
            if not price_1 and single_price:
                price_1 = float(single_price)

            if price_1:
                price_10 = price_10 or price_1
                price_100 = price_100 or price_1

                savings_100 = 0.0
                if price_1 > 0 and price_100 < price_1:
                    savings_100 = round((1 - price_100 / price_1) * 100, 1)

                if savings_100 >= 20:
                    alerts.append(
                        {
                            "designators": row.get("designators", ""),
                            "lcsc_pn": lcsc_pn,
                            "price_1": price_1,
                            "price_10": price_10,
                            "price_100": price_100,
                            "savings_pct_100": savings_100,
                        }
                    )
        except Exception:
            continue

    return alerts


def _parse_price(raw: str | float | int | None) -> float:
    """Parse a price string to float, returning 0.0 on failure."""
    if raw is None:
        return 0.0
    if isinstance(raw, (int, float)):
        return float(raw)
    try:
        return float(str(raw).strip().replace("$", "").replace(",", ""))
    except (ValueError, AttributeError):
        return 0.0


def _append_price_breaks(readme_path: Path, alerts: list[dict]) -> None:
    """Append price-break cost-saving tips to the assembly README."""
    lines = [
        "",
        "=" * 60,
        "PRICE-BREAK ALERTS — Cost-saving opportunities",
        "=" * 60,
        "",
        "The following components have significant price breaks at higher quantity:",
        "",
    ]
    for alert in sorted(alerts, key=lambda a: -a["savings_pct_100"]):
        refs = alert["designators"]
        pn = alert["lcsc_pn"]
        p1 = alert["price_1"]
        p100 = alert["price_100"]
        savings = alert["savings_pct_100"]
        lines.append(f"  {refs} ({pn}):")
        lines.append(f"    \u2022 ${p1:.4f} @ qty 1")
        lines.append(f"    \u2022 ${p100:.4f} @ qty 100 (save {savings:.0f}%)")
        lines.append("")

    try:
        with open(readme_path, "a", encoding="utf-8") as f:
            f.write("\n".join(lines))
    except OSError:
        pass


def export_jlcpcb(
    spec: dict[str, Any],
    output_dir: str | Path,
    enrich_parts: bool = False,
    assembly_variants: list[dict[str, Any]] | None = None,
    pcb_path: str | Path | None = None,
    identity_bundles_by_reference: Mapping[str, Any] | None = None,
    evidence_ids_by_reference: Mapping[str, Iterable[str]] | None = None,
    evidence_ids_by_artifact: Mapping[str, Iterable[str]] | None = None,
    evidence_ids: Iterable[str] = (),
    evidence_manifest: str = "",
) -> dict[str, Any]:
    """Export an exhaustive JLCPCB BOM and, when safe, a physical-board CPL.

    Args:
        spec: Design spec dict (same format as passed to validate_design)
        output_dir: Directory to write BOM/CPL/README files
        enrich_parts: (reserved for future use) Whether to enrich part info via APIs
        assembly_variants: Optional assembly variants. Each item may contain
            name, include_refs, exclude_refs, and dnp_refs.
        pcb_path: A real, pad-bearing ``.kicad_pcb`` file. If omitted, export
            succeeds as BOM-only and reports why no CPL was produced. Placement
            preview and padless boards are rejected.
        evidence_ids_by_reference: Optional real evidence IDs keyed by designator.
        evidence_ids_by_artifact: Optional real evidence IDs keyed by delivery artifact kind.
        evidence_ids: Optional real delivery-level evidence IDs.
        evidence_manifest: Optional output-relative evidence manifest reference.

    Returns:
        Summary dict: {
            "status": "ok" | "bom_only" | "blocked" | "error",
            "message": str,
            "files": [...],
            "component_count": int,
            "bom_rows": int,
            "missing_lcsc": int,
        }
    """
    publish_dir = Path(output_dir)
    staging_dir: Path | None = None
    lock_stack = ExitStack()
    lock_acquired = False
    try:
        from .dispatcher import compile_design_ir

        publish_dir.mkdir(parents=True, exist_ok=True)
        # Hold the lock from the previous-manifest read through publication or
        # cleanup.  Otherwise two individually atomic exports can still combine
        # files from different design generations.
        lock_stack.enter_context(_delivery_output_lock(publish_dir))
        lock_acquired = True
        previous_manifest_path = publish_dir / "assembly_manifest.json"

        # Step 1: Compile the design
        compiled = compile_design_ir(spec, enrich_parts=enrich_parts)
        components = compiled.components
        project_name = spec.get("project", "Design")

        # Step 2: Build the one canonical inventory used by all delivery files.
        assembly_manifest = build_assembly_manifest(
            components,
            previous_manifest=previous_manifest_path if previous_manifest_path.is_file() else None,
            evidence_ids_by_reference=evidence_ids_by_reference,
            evidence_ids=evidence_ids,
            evidence_manifest=evidence_manifest,
        )
        artifact_evidence = {
            str(kind): tuple(str(evidence_id) for evidence_id in identifiers)
            for kind, identifiers in (evidence_ids_by_artifact or {}).items()
        }
        bom_rows = group_bom_rows(assembly_manifest)
        active_bom_items = assembly_manifest.active_bom_items()
        active_cpl_items = assembly_manifest.active_cpl_items()

        # Step 3: Detect price breaks
        price_breaks = _detect_price_breaks(bom_rows)

        # Step 4: Build the complete delivery in a private directory.  Nothing
        # becomes public until all artifacts and the delivery state agree.
        staging_dir = publish_dir / f".cw-jlc-{uuid.uuid4().hex}"
        staging_dir.mkdir()
        staged_bom_path = staging_dir / "bom_jlcpcb.csv"
        staged_cpl_path = staging_dir / "cpl_jlcpcb.csv"
        staged_readme_path = staging_dir / "README_jlcpcb.txt"
        staged_assembly_manifest_path = staging_dir / "assembly_manifest.json"
        staged_delivery_manifest_path = staging_dir / "delivery_manifest.json"

        bom_path = publish_dir / staged_bom_path.name
        cpl_path = publish_dir / staged_cpl_path.name
        readme_path = publish_dir / staged_readme_path.name
        assembly_manifest_path = publish_dir / staged_assembly_manifest_path.name
        delivery_manifest_path = publish_dir / staged_delivery_manifest_path.name

        assembly_manifest.write_json(staged_assembly_manifest_path)
        write_jlcpcb_bom(bom_rows, staged_bom_path)

        # Step 5: Write variant BOMs from the same exhaustive manifest.
        variant_outputs: list[dict[str, Any]] = []
        if assembly_variants:
            for variant in generate_assembly_variants(assembly_manifest, assembly_variants):
                token = variant["token"]
                staged_variant_bom = staging_dir / f"bom_jlcpcb_{token}.csv"
                variant_bom = publish_dir / staged_variant_bom.name
                write_jlcpcb_bom(variant["bom_rows"], staged_variant_bom)
                variant_outputs.append(
                    {
                        "name": variant["name"],
                        "bom": str(variant_bom),
                        "cpl": "",
                        "component_count": len(variant["components"]),
                        "bom_rows": len(variant["bom_rows"]),
                        "dnp_refs": variant["dnp_refs"],
                        "_items": variant["components"],
                        "_token": token,
                    }
                )

        # Step 6: CPL is allowed only from a real board that reconciles with
        # every active assembly item. No synthetic placement is generated here.
        blocked_reasons: list[str] = []
        cpl_generated = False
        placements: dict[str, tuple[float, float, float, str]] = {}
        if not active_bom_items:
            blocked_reasons.append("Assembly manifest has no active BOM items")
        if not active_cpl_items:
            blocked_reasons.append("Assembly manifest has no active placement references")
        missing_footprints = assembly_manifest.missing_footprint_refs()
        if missing_footprints:
            blocked_reasons.append("Assembly items missing footprints: " + ", ".join(missing_footprints[:12]))

        if pcb_path is None:
            blocked_reasons.append(
                "CPL not generated: provide a real, pad-bearing .kicad_pcb; placement previews are review-only"
            )
        elif active_cpl_items and not missing_footprints:
            identity_blockers: list[str] = []
            for item in active_cpl_items:
                if item.source_kind != "component":
                    continue
                bundle = (identity_bundles_by_reference or {}).get(item.reference)
                if bundle is None:
                    identity_blockers.append(f"CW-ID-001 {item.reference}: missing identity handoff bundle")
                    continue
                try:
                    result = bundle.evaluate()
                    if not result.ready or bundle.footprint_ref != item.footprint:
                        codes = result.blocker_codes or ("CW-ID-001",)
                        identity_blockers.append(f"{','.join(codes)} {item.reference}: identity/footprint not ready")
                except (AttributeError, ValueError):
                    identity_blockers.append(f"CW-ID-001 {item.reference}: invalid identity handoff bundle")
            if identity_blockers:
                blocked_reasons.extend(f"CPL not generated: {reason}" for reason in identity_blockers)
            else:
                required_refs = {item.reference for item in active_cpl_items}
                expected_footprints = {item.reference: item.footprint for item in active_cpl_items}
                try:
                    placements = parse_pcb_placements(
                        pcb_path,
                        required_refs=required_refs,
                        expected_footprints=expected_footprints,
                    )
                    write_jlcpcb_cpl(active_cpl_items, placements, staged_cpl_path)
                    cpl_generated = True
                except CplSourceError as exc:
                    blocked_reasons.append(f"CPL not generated: {exc}")
        elif not active_cpl_items:
            blocked_reasons.append("CPL not generated: assembly has no active placement references")

        if cpl_generated:
            for variant_output in variant_outputs:
                staged_variant_cpl = staging_dir / f"cpl_jlcpcb_{variant_output.pop('_token')}.csv"
                variant_cpl = publish_dir / staged_variant_cpl.name
                variant_items = variant_output.pop("_items")
                write_jlcpcb_cpl(variant_items, placements, staged_variant_cpl)
                variant_output["cpl"] = str(variant_cpl)
        else:
            for variant_output in variant_outputs:
                variant_output.pop("_token")
                variant_output.pop("_items")

        missing_lcsc = sum(1 for row in bom_rows if not row["has_lcsc"])
        if missing_lcsc:
            blocked_reasons.append(f"{missing_lcsc} BOM row(s) have no LCSC part number and require explicit sourcing")

        assembly_ready = bool(active_bom_items) and bool(active_cpl_items) and cpl_generated
        assembly_ready = assembly_ready and not missing_lcsc and not missing_footprints
        # This exporter validates only BOM/CPL reconciliation. It does not run
        # board DRC or generate/inspect Gerbers, so it must never claim the
        # complete design is fabrication-ready.
        fabrication_ready = False
        if not active_bom_items:
            status = "blocked"
        elif pcb_path is None:
            status = "bom_only"
        elif assembly_ready:
            status = "ok"
        else:
            status = "blocked"

        write_jlcpcb_readme(
            project_name,
            staged_readme_path,
            cpl_included=cpl_generated,
            blocked_reasons=blocked_reasons,
        )
        if price_breaks:
            _append_price_breaks(staged_readme_path, price_breaks)

        delivery_artifacts = [
            DeliveryArtifact(
                "assembly_manifest",
                assembly_manifest_path.name,
                "ready",
                evidence_ids=artifact_evidence.get("assembly_manifest", ()),
            ),
            DeliveryArtifact(
                "bom",
                bom_path.name,
                "ready" if active_bom_items else "blocked",
                reason="" if active_bom_items else "Assembly manifest has no active BOM items",
                evidence_ids=artifact_evidence.get("bom", ()),
            ),
            DeliveryArtifact(
                "cpl",
                cpl_path.name,
                "ready" if cpl_generated else ("omitted" if pcb_path is None else "blocked"),
                reason=""
                if cpl_generated
                else next(
                    (reason for reason in blocked_reasons if reason.startswith("CPL not generated")),
                    "CPL generation prerequisites were not met",
                ),
                evidence_ids=artifact_evidence.get("cpl", ()),
            ),
            DeliveryArtifact("readme", readme_path.name, "ready", evidence_ids=artifact_evidence.get("readme", ())),
        ]
        for variant_output in variant_outputs:
            delivery_artifacts.append(
                DeliveryArtifact(
                    "variant_bom",
                    Path(variant_output["bom"]).name,
                    "ready",
                    evidence_ids=artifact_evidence.get("variant_bom", ()),
                )
            )
            if variant_output["cpl"]:
                delivery_artifacts.append(
                    DeliveryArtifact(
                        "variant_cpl",
                        Path(variant_output["cpl"]).name,
                        "ready",
                        evidence_ids=artifact_evidence.get("variant_cpl", ()),
                    )
                )
        delivery = DeliveryManifest(
            status=status,
            assembly_ready=assembly_ready,
            fabrication_ready=fabrication_ready,
            assembly_item_count=len(assembly_manifest.items),
            artifacts=delivery_artifacts,
            blocked_reasons=blocked_reasons,
            warnings=[
                "BOM/CPL export does not establish fabrication readiness; run board DRC and verify Gerber/drill files"
            ],
            evidence_ids=tuple(str(evidence_id) for evidence_id in evidence_ids),
            evidence_manifest=evidence_manifest,
        )
        delivery.write_json(staged_delivery_manifest_path)

        files = [
            str(bom_path),
            str(assembly_manifest_path),
            str(delivery_manifest_path),
            str(readme_path),
            *[item["bom"] for item in variant_outputs],
        ]
        if cpl_generated:
            files.insert(1, str(cpl_path))
            files.extend(item["cpl"] for item in variant_outputs if item["cpl"])

        if status == "ok":
            message = f"Exported reconciled JLCPCB BOM and CPL for {project_name}"
        elif status == "bom_only":
            message = f"Exported exhaustive BOM for {project_name}; CPL requires a physical PCB"
        else:
            message = f"Exported BOM for {project_name}; assembly delivery is blocked"

        # Publish only after all paths, statuses, and artifact contents agree.
        # The helper moves delivery_manifest.json last as the commit marker.
        _publish_delivery_staging(staging_dir, publish_dir, _lock_held=True)
        staging_dir = None

        return {
            "status": status,
            "message": message,
            "files": files,
            "component_count": len(components),
            "assembly_item_count": len(assembly_manifest.items),
            "bom_rows": len(bom_rows),
            "missing_lcsc": missing_lcsc,
            "price_breaks": len(price_breaks),
            "assembly_variants": variant_outputs,
            "assembly_manifest": str(assembly_manifest_path),
            "delivery_manifest": str(delivery_manifest_path),
            "evidence_manifest": evidence_manifest,
            "cpl": str(cpl_path) if cpl_generated else "",
            "pcb_source": str(pcb_path) if pcb_path is not None else "",
            "assembly_ready": assembly_ready,
            "fabrication_ready": fabrication_ready,
            "blocked_reasons": blocked_reasons,
        }

    except Exception as exc:
        if staging_dir is not None:
            shutil.rmtree(staging_dir, ignore_errors=True)
        # Old output is not a valid fallback for a failed new export.  Removing
        # every exporter-owned file prevents stale CPL/BOM variants from being
        # mistaken for the requested delivery; unrelated user files remain.
        if lock_acquired:
            _remove_owned_delivery_files(publish_dir)
        return {
            "status": "error",
            "message": str(exc),
            "files": [],
            "component_count": 0,
            "bom_rows": 0,
            "missing_lcsc": 0,
        }
    finally:
        lock_stack.close()
