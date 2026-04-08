"""Automatic test point generation for circuit-weaver designs.

Identifies key nets (power rails, differential pairs, clocks, data buses, ground)
from a DesignIR and emits a ``{project_name}_test_points.csv`` alongside the
generated schematic artifacts.  Optionally annotates the schematic content with
lightweight text labels so each test point is traceable back to a net.

CSV columns: TestPoint, Net, Type, Priority
Types: power_rail | differential | clock | data_bus | ground
"""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .design_ir import DesignIR

# ---------------------------------------------------------------------------
# Net classification patterns
# ---------------------------------------------------------------------------

_POWER_PREFIXES: tuple[str, ...] = (
    "VDD",
    "VCC",
    "VBUS",
    "VBAT",
    "VSYS",
    "V3V3",
    "V5V",
    "V1V8",
    "V3V",
    "V5",
    "PVDD",
    "AVDD",
    "DVDD",
)
_GROUND_NAMES: frozenset[str] = frozenset({"GND", "GNDA", "DGND", "AGND", "PGND"})
_GROUND_PREFIXES: tuple[str, ...] = ("GND", "AGND", "DGND", "PGND")

_CLOCK_RE: list[re.Pattern[str]] = [
    re.compile(r"CLK", re.I),
    re.compile(r"XTAL", re.I),
    re.compile(r"OSC", re.I),
    re.compile(r"MCK", re.I),
]
_DATA_BUS_RE: list[re.Pattern[str]] = [
    re.compile(r"SPI", re.I),
    re.compile(r"I2C", re.I),
    re.compile(r"UART", re.I),
    re.compile(r"\bCAN\b", re.I),
    re.compile(r"USB", re.I),
    re.compile(r"MISO|MOSI|COPI|CIPO|SDI|SDO", re.I),
]
_DIFF_SUFFIXES: tuple[tuple[str, str], ...] = (
    ("_P", "_N"),
    ("+", "-"),
    ("_DP", "_DN"),
)


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class TestPoint:
    """A single test point to expose on the PCB or schematic."""

    name: str  # TP1, TP2, …
    net: str  # KiCad net name
    tp_type: str  # power_rail | differential | clock | data_bus | ground
    priority: str  # high | medium | low


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _classify_net(net: str) -> tuple[str, str] | None:
    """Return (type, priority) for *net*, or ``None`` if not a test-point candidate."""
    net_upper = net.upper()

    # Ground (most critical — always expose)
    if net_upper in _GROUND_NAMES or any(net_upper.startswith(p) for p in _GROUND_PREFIXES):
        return ("ground", "high")

    # Power rails
    if any(net_upper.startswith(p) for p in _POWER_PREFIXES):
        return ("power_rail", "high")

    # Clock / crystal signals
    if any(pattern.search(net) for pattern in _CLOCK_RE):
        return ("clock", "high")

    # Data bus signals
    if any(pattern.search(net) for pattern in _DATA_BUS_RE):
        return ("data_bus", "medium")

    return None


def _collect_nets(design_ir: DesignIR) -> set[str]:
    """Return all net names visible in the DesignIR."""
    nets: set[str] = set()

    for iface in design_ir.interfaces:
        if iface.name:
            nets.add(iface.name)

    for block in design_ir.blocks:
        for iface in block.interfaces:
            if iface.name:
                nets.add(iface.name)
        if block.params:
            for key in ("net", "power_net", "rail", "vdd_net", "gnd_net"):
                val = block.params.get(key)
                if val:
                    nets.add(str(val))

    return nets


def _collect_diff_pairs(design_ir: DesignIR) -> list[tuple[str, str]]:
    """Return ``(positive_net, negative_net)`` pairs from pcb_constraints and net naming."""
    pairs: list[tuple[str, str]] = []

    # Explicit diff_pair constraints
    for constraint in design_ir.pcb_constraints:
        if constraint.get("kind") == "diff_pair":
            target = str(constraint.get("target", ""))
            parts = [p.strip() for p in target.split(",") if p.strip()]
            if len(parts) == 2:
                pairs.append((parts[0], parts[1]))
            elif len(parts) == 1:
                pos = parts[0]
                for pos_sfx, neg_sfx in _DIFF_SUFFIXES:
                    if pos.endswith(pos_sfx):
                        neg = pos[: -len(pos_sfx)] + neg_sfx
                        pairs.append((pos, neg))
                        break

    # Infer from interface net names
    all_nets = _collect_nets(design_ir)
    for net in sorted(all_nets):
        for pos_sfx, neg_sfx in _DIFF_SUFFIXES:
            if net.endswith(pos_sfx):
                neg = net[: -len(pos_sfx)] + neg_sfx
                if neg in all_nets and (net, neg) not in pairs:
                    pairs.append((net, neg))

    return pairs


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def generate_test_points(design_ir: DesignIR) -> list[TestPoint]:
    """Generate a list of :class:`TestPoint` from a :class:`DesignIR`.

    Returned in priority order: ground → power_rail → clock → data_bus → differential.
    """
    result: list[TestPoint] = []
    seen: set[str] = set()
    counter = 1

    # Classified nets (power rails, ground, clock, data buses)
    nets = _collect_nets(design_ir)
    for net in sorted(nets):
        if net in seen:
            continue
        classification = _classify_net(net)
        if classification:
            tp_type, priority = classification
            result.append(TestPoint(name=f"TP{counter}", net=net, tp_type=tp_type, priority=priority))
            seen.add(net)
            counter += 1

    # Differential pairs not already covered
    for pos_net, neg_net in _collect_diff_pairs(design_ir):
        for net in (pos_net, neg_net):
            if net not in seen:
                result.append(TestPoint(name=f"TP{counter}", net=net, tp_type="differential", priority="high"))
                seen.add(net)
                counter += 1

    return result


def write_test_points_csv(test_points: list[TestPoint], output_path: str | Path) -> Path:
    """Write *test_points* to a CSV at *output_path* and return the path."""
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=["TestPoint", "Net", "Type", "Priority"])
        writer.writeheader()
        for tp in test_points:
            writer.writerow({"TestPoint": tp.name, "Net": tp.net, "Type": tp.tp_type, "Priority": tp.priority})
    return out


def annotate_schematic(schematic_content: str, test_points: list[TestPoint]) -> str:
    """Insert test-point text annotations into a ``.kicad_sch`` content string.

    Each annotation is a KiCad ``(text ...)`` element placed in a block at the
    top-left of the schematic space.  The annotations carry no connectivity —
    they are purely informational labels for the reviewer.
    """
    if not test_points:
        return schematic_content

    annotations: list[str] = []
    for idx, tp in enumerate(test_points):
        y = 10.0 + idx * 2.54
        label = f"{tp.name}: {tp.net} [{tp.tp_type}]"
        annotations.append(f'  (text "{label}" (at 2.54 {y:.2f} 0)\n    (effects (font (size 1.27 1.27))))')

    annotation_block = "\n".join(annotations) + "\n"

    # Insert before the closing paren of the kicad_sch root form
    stripped = schematic_content.rstrip()
    if stripped.endswith(")"):
        return stripped[:-1] + "\n" + annotation_block + ")\n"

    return schematic_content + "\n" + annotation_block


def generate_test_point_artifacts(
    design_ir: DesignIR,
    output_dir: str | Path,
    project_name: str,
    schematic_path: str | Path | None = None,
) -> dict[str, Any]:
    """Generate all test-point artifacts and return a result summary dict.

    Args:
        design_ir: Compiled DesignIR for the design.
        output_dir: Directory where the CSV (and annotated schematic) are written.
        project_name: Used as the CSV filename stem.
        schematic_path: If provided, the root ``.kicad_sch`` is read, annotated
            with test-point labels, and written back in place.

    Returns:
        Dict with keys: ``csv_path`` (str), ``test_point_count`` (int),
        ``test_points`` (list[dict]), ``annotated_schematic`` (bool).
    """
    output_dir = Path(output_dir)
    test_points = generate_test_points(design_ir)

    csv_path = output_dir / f"{project_name}_test_points.csv"
    write_test_points_csv(test_points, csv_path)

    annotated = False
    if schematic_path is not None:
        sch = Path(schematic_path)
        if sch.exists():
            content = sch.read_text(encoding="utf-8")
            annotated_content = annotate_schematic(content, test_points)
            if annotated_content != content:
                sch.write_text(annotated_content, encoding="utf-8")
                annotated = True

    return {
        "csv_path": str(csv_path),
        "test_point_count": len(test_points),
        "test_points": [
            {"name": tp.name, "net": tp.net, "type": tp.tp_type, "priority": tp.priority} for tp in test_points
        ],
        "annotated_schematic": annotated,
    }
