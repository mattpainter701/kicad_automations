"""Design documentation generator — auto-generate assembly guides and ordering files.

Produces:
- Assembly guide: component list, placement diagram, soldering notes
- Ordering checklist: per-distributor order files
- Component datasheet index: links to downloaded datasheets
- Power budget: CSV with rail voltage, current, dissipation
"""

from __future__ import annotations

import csv
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .design_ir import DesignIR

logger = logging.getLogger(__name__)


@dataclass
class AssemblyGuideConfig:
    """Configuration for assembly guide generation."""

    include_placement_svg: bool = True
    include_datasheet_links: bool = True
    include_soldering_notes: bool = True
    group_by_category: bool = True
    page_size: str = "A4"  # A4 or letter


def _generate_bom_table(design_ir: DesignIR) -> list[dict[str, Any]]:
    """Extract BOM data from design IR.

    Returns list of dicts: {reference, value, footprint, mpn, manufacturer, category}
    """
    bom = []
    components = getattr(design_ir, "components", None)
    if isinstance(components, dict):
        for comp_id, comp in components.items():
            bom.append(
                {
                    "reference": comp_id,
                    "value": comp.value or comp.mpn or "N/A",
                    "footprint": comp.footprint or "N/A",
                    "mpn": comp.mpn or "UNRESOLVED",
                    "manufacturer": comp.source_manufacturer or "Unknown",
                    "category": comp.category or "Miscellaneous",
                    "quantity": 1,  # Simplified; would need BOM grouping
                }
            )
        return sorted(bom, key=lambda x: (x["category"], x["reference"]))

    for block in getattr(design_ir, "blocks", []):
        part_bindings = block.part_bindings or {}
        mpn = str(part_bindings.get("mpn") or block.mpn or block.ic or "").strip()
        if not (block.ref or mpn or block.value):
            continue
        bom.append(
            {
                "reference": block.ref or block.id,
                "value": block.value or mpn or "N/A",
                "footprint": str(part_bindings.get("footprint") or "").strip() or "N/A",
                "mpn": mpn or "UNRESOLVED",
                "manufacturer": str(part_bindings.get("manufacturer") or "").strip() or "Unknown",
                "category": block.section or "Miscellaneous",
                "quantity": 1,
            }
        )
    return sorted(bom, key=lambda x: (x["category"], x["reference"]))


def _generate_power_budget(design_ir: DesignIR) -> list[dict[str, Any]]:
    """Extract power budget from design IR.

    Returns list of dicts: {rail_name, voltage, estimated_current_ma, power_w}
    """
    budget = []

    # A typed power-domain declaration is authoritative.  It is deliberately
    # not supplemented with category-derived estimates: unknown current or
    # voltage remains unknown in the handoff document.
    typed_domains = list(getattr(design_ir, "power_domains", []) or [])
    if typed_domains:
        for domain in sorted(typed_domains, key=lambda item: str(getattr(item, "net", ""))):
            nominal = getattr(domain, "v_nominal", None)
            steady = getattr(domain, "i_steady_ma", None)
            power_w = None
            if isinstance(nominal, (int, float)) and isinstance(steady, (int, float)):
                power_w = round(nominal * steady / 1000, 6)
            budget.append(
                {
                    "rail": getattr(domain, "net", ""),
                    "voltage": nominal,
                    "current_ma": steady,
                    "power_w": power_w,
                    "v_min": getattr(domain, "v_min", None),
                    "v_nominal": nominal,
                    "v_max": getattr(domain, "v_max", None),
                    "direction": getattr(domain, "direction", None),
                    "i_steady_ma": steady,
                    "i_peak_ma": getattr(domain, "i_peak_ma", None),
                    "sequence_order": getattr(domain, "sequence_order", None),
                    "sequence_dependency": getattr(domain, "sequence_dependency", None),
                    "tolerance": getattr(domain, "tolerance", None),
                    "evidence_id": getattr(domain, "evidence_id", None),
                }
            )
        return budget

    # Estimate power per IC based on category and typical specs
    power_map = {
        "mcu": 0.1,  # 100mW typical for MCU at 3.3V
        "fpga": 0.5,  # 500mW for small FPGA
        "wifi": 0.2,  # 200mW for WiFi module
        "bluetooth": 0.1,  # 100mW for BLE
        "sensor": 0.01,  # 10mW for typical sensor
        "regulator": 0.05,  # 50mW quiescent + efficiency loss
    }

    rail_power = {}
    components = getattr(design_ir, "components", None)
    if isinstance(components, dict):
        iterable = [(comp.category or "").lower() for comp in components.values()]
    else:
        iterable = []
        for block in getattr(design_ir, "blocks", []):
            descriptor = " ".join(
                [
                    str(block.section or ""),
                    str(block.template_type or ""),
                    str(block.ic or ""),
                    str(block.mpn or ""),
                    str(block.description or ""),
                ]
            ).lower()
            if "stm32" in descriptor or "esp32" in descriptor or "mcu" in descriptor:
                iterable.append("mcu")
            elif "fpga" in descriptor or "zynq" in descriptor:
                iterable.append("fpga")
            elif "wifi" in descriptor:
                iterable.append("wifi")
            elif "bluetooth" in descriptor or "ble" in descriptor:
                iterable.append("bluetooth")
            elif "sensor" in descriptor:
                iterable.append("sensor")
            elif "regulator" in descriptor or "buck" in descriptor or "boost" in descriptor or "ldo" in descriptor:
                iterable.append("regulator")

    for category in iterable:
        if category in power_map:
            power_w = power_map[category]
            # Estimate current at 3.3V (would need actual rail voltage)
            current_ma = (power_w / 3.3) * 1000 if power_w > 0 else 0
            rail = "VDD_3V3"  # Simplified assumption
            if rail not in rail_power:
                rail_power[rail] = {"voltage": 3.3, "current": 0}
            rail_power[rail]["current"] += current_ma

    for rail, data in rail_power.items():
        budget.append(
            {
                "rail": rail,
                "voltage": data["voltage"],
                "current_ma": round(data["current"], 1),
                "power_w": round(data["voltage"] * data["current"] / 1000, 3),
            }
        )

    return sorted(budget, key=lambda x: x["rail"])


def generate_assembly_guide_csv(
    design_ir: DesignIR,
    output_path: str | Path,
) -> Path:
    """Generate assembly guide as CSV.

    Output columns: Reference, Value, Footprint, MPN, Manufacturer, Category, Quantity

    Args:
        design_ir: Compiled design IR
        output_path: Path to write CSV

    Returns:
        Path to generated CSV file
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    bom = _generate_bom_table(design_ir)

    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "Reference",
                "Value",
                "Footprint",
                "MPN",
                "Manufacturer",
                "Category",
                "Quantity",
            ],
        )
        writer.writeheader()
        for item in bom:
            writer.writerow(
                {
                    "Reference": item["reference"],
                    "Value": item["value"],
                    "Footprint": item["footprint"],
                    "MPN": item["mpn"],
                    "Manufacturer": item["manufacturer"],
                    "Category": item["category"],
                    "Quantity": item["quantity"],
                }
            )

    logger.info(f"Assembly guide CSV written to {output_path}")
    return output_path


def generate_power_budget_csv(
    design_ir: DesignIR,
    output_path: str | Path,
) -> Path:
    """Generate power budget spreadsheet as CSV.

    Output columns: Rail, Voltage, Current (mA), Power (W)

    Args:
        design_ir: Compiled design IR
        output_path: Path to write CSV

    Returns:
        Path to generated CSV file
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    budget = _generate_power_budget(design_ir)

    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "Rail", "Voltage", "Current (mA)", "Power (W)", "Vmin (V)", "Vnom (V)", "Vmax (V)",
                "Direction", "Peak (mA)", "Sequence Order", "Sequence Dependency", "Tolerance", "Evidence ID",
            ],
        )
        writer.writeheader()
        for item in budget:
            writer.writerow(
                {
                    "Rail": item["rail"],
                    "Voltage": item.get("voltage", ""),
                    "Current (mA)": item.get("current_ma", ""),
                    "Power (W)": item.get("power_w", ""),
                    "Vmin (V)": item.get("v_min", ""),
                    "Vnom (V)": item.get("v_nominal", ""),
                    "Vmax (V)": item.get("v_max", ""),
                    "Direction": item.get("direction", ""),
                    "Peak (mA)": item.get("i_peak_ma", ""),
                    "Sequence Order": item.get("sequence_order", ""),
                    "Sequence Dependency": item.get("sequence_dependency", ""),
                    "Tolerance": item.get("tolerance", ""),
                    "Evidence ID": item.get("evidence_id", ""),
                }
            )

    logger.info(f"Power budget CSV written to {output_path}")
    return output_path


def generate_ordering_checklist(
    design_ir: DesignIR,
    output_path: str | Path,
) -> Path:
    """Generate ordering checklist for assembly.

    Markdown format with checkboxes for each distributor and per-part status.

    Args:
        design_ir: Compiled design IR
        output_path: Path to write markdown

    Returns:
        Path to generated markdown file
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    bom = _generate_bom_table(design_ir)

    lines = [
        "# Ordering Checklist",
        "",
        "## By Distributor",
        "",
        "- [ ] DigiKey",
        "- [ ] Mouser",
        "- [ ] LCSC",
        "",
        "## Component Status",
        "",
        "| Ref | Value | Footprint | MPN | Status |",
        "|-----|-------|-----------|-----|--------|",
    ]

    for item in bom:
        status = "✓ Sourced" if item["mpn"] != "UNRESOLVED" else "⚠️ Unresolved"
        lines.append(f"| {item['reference']} | {item['value']} | {item['footprint']} | {item['mpn']} | {status} |")

    lines.extend(
        [
            "",
            "## Notes",
            "",
            "- Check stock levels and lead times before ordering",
            "- Consolidate orders to minimize shipping costs",
            "- Consider ordering 10-20% spare parts for rework",
        ]
    )

    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    logger.info(f"Ordering checklist written to {output_path}")
    return output_path


def generate_datasheet_index(
    datasheets_dir: str | Path,
    output_path: str | Path,
) -> Path:
    """Generate datasheet index referencing all available datasheets.

    Creates a markdown file linking to each datasheet found in directory.

    Args:
        datasheets_dir: Directory containing downloaded PDFs
        output_path: Path to write markdown index

    Returns:
        Path to generated index file
    """
    datasheets_dir = Path(datasheets_dir)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Find all PDFs
    pdfs = sorted(datasheets_dir.glob("*.pdf"))

    lines = [
        "# Datasheet Index",
        "",
        "## Available Datasheets",
        "",
    ]

    for pdf in pdfs:
        mpn = pdf.stem
        lines.append(f"- [{mpn}]({pdf.name}) — {pdf.stat().st_size / 1024:.0f} KB")

    if not pdfs:
        lines.append("_No datasheets found. Run `circuit-weaver sync-datasheets` to download._")

    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    logger.info(f"Datasheet index written to {output_path}")
    return output_path


def generate_all_docs(
    design_ir: DesignIR,
    output_dir: str | Path,
    datasheets_dir: str | Path | None = None,
) -> dict[str, Path]:
    """Generate all design documentation files.

    Args:
        design_ir: Compiled design IR
        output_dir: Directory to write all files
        datasheets_dir: Optional directory with downloaded datasheets

    Returns:
        Dict of {file_type: output_path} for all generated files
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    results = {}

    # Generate assembly guide
    results["assembly_guide"] = generate_assembly_guide_csv(
        design_ir,
        output_dir / "assembly_guide.csv",
    )

    # Generate power budget
    results["power_budget"] = generate_power_budget_csv(
        design_ir,
        output_dir / "power_budget.csv",
    )

    # Generate ordering checklist
    results["ordering_checklist"] = generate_ordering_checklist(
        design_ir,
        output_dir / "ordering_checklist.md",
    )

    # Generate datasheet index if directory provided
    if datasheets_dir and Path(datasheets_dir).exists():
        results["datasheet_index"] = generate_datasheet_index(
            datasheets_dir,
            output_dir / "datasheet_index.md",
        )

    logger.info(f"Design documentation generated in {output_dir}")
    return results
