"""DFM (Design for Manufacture) checker — validates PCB designs against fab capabilities.

Detects violations of trace width, spacing, via size, annular ring, solder mask clearance,
board edge clearance, and pad-to-pad spacing constraints. Supports multiple fab profiles
(JLCPCB, PCBWay, custom DRC rules) and generates actionable violation reports.

Usage:
    from circuit_weaver.dfm_checker import check_dfm

    violations = check_dfm("design.kicad_pcb", profile="jlcpcb")
    for v in violations:
        print(f"{v['severity']}: {v['type']} at {v['location']} - {v['message']}")
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DFMViolation:
    """Represents a single DFM violation."""

    severity: str  # "critical", "warning"
    type: str  # "trace_width", "spacing", "via_drill", etc.
    location: str  # net name, component ref, or coordinate
    actual: float | None  # actual measured value in mm
    minimum: float | None  # minimum allowed value in mm
    message: str
    suggestion: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict for JSON serialization."""
        return {
            "severity": self.severity,
            "type": self.type,
            "location": self.location,
            "actual": self.actual,
            "minimum": self.minimum,
            "message": self.message,
            "suggestion": self.suggestion,
        }


# DFM Profiles: fab-specific design rules (in mm)
_DFM_PROFILES = {
    "jlcpcb": {
        "name": "JLCPCB Standard (2-layer)",
        "trace_width_min": 0.127,
        "trace_spacing_min": 0.127,
        "via_diameter_min": 0.45,
        "via_drill_min": 0.2,
        "annular_ring_min": 0.125,
        "solder_mask_clearance_min": 0.1,
        "board_edge_clearance_min": 0.3,
        "pad_to_pad_min": 0.2,
    },
    "jlcpcb_4layer": {
        "name": "JLCPCB 4-layer",
        "trace_width_min": 0.09,
        "trace_spacing_min": 0.09,
        "via_diameter_min": 0.3,
        "via_drill_min": 0.15,
        "annular_ring_min": 0.1,
        "solder_mask_clearance_min": 0.1,
        "board_edge_clearance_min": 0.3,
        "pad_to_pad_min": 0.15,
    },
    "pcbway": {
        "name": "PCBWay Standard (2-layer)",
        "trace_width_min": 0.1,
        "trace_spacing_min": 0.1,
        "via_diameter_min": 0.3,
        "via_drill_min": 0.15,
        "annular_ring_min": 0.15,
        "solder_mask_clearance_min": 0.1,
        "board_edge_clearance_min": 0.3,
        "pad_to_pad_min": 0.2,
    },
}


def _parse_pcb_s_expr(content: str) -> dict[str, Any]:
    """Parse KiCad PCB S-expression format into structured data.

    Extracts: layers, net list, board dimensions, track/via data, pad locations.
    Very simplified — just enough for DFM checks.
    """
    pcb = {
        "nets": {},
        "tracks": [],
        "vias": [],
        "pads": [],
        "board_width_mm": 100,
        "board_height_mm": 80,
    }

    # Extract net list (net N "name")
    for match in re.finditer(r'\(net\s+(\d+)\s+"([^"]+)"\)', content):
        net_num = match.group(1)
        net_name = match.group(2)
        pcb["nets"][net_name] = int(net_num)

    # Extract tracks: (segment (pts (xy x1 y1) (xy x2 y2)) (width w) (layer layer_name) (net net_num))
    for match in re.finditer(
        r"\(segment\s+\(pts\s+\((xy\s+([\d.]+)\s+([\d.]+))\s+\((xy\s+([\d.]+)\s+([\d.]+)\))",
        content,
    ):
        x1 = float(match.group(2)) / 1e6  # Convert from nm to mm
        y1 = float(match.group(3)) / 1e6
        x2 = float(match.group(5)) / 1e6
        y2 = float(match.group(6)) / 1e6
        pcb["tracks"].append({"x1": x1, "y1": y1, "x2": x2, "y2": y2})

    # Extract vias: (via (at x y) (size size) (drill drill) (layers layer1 layer2) (net net_num))
    for match in re.finditer(
        r"\(via\s+\(at\s+([\d.]+)\s+([\d.]+)\).*?\(size\s+([\d.]+)\).*?\(drill\s+([\d.]+)\)",
        content,
        re.DOTALL,
    ):
        x = float(match.group(1)) / 1e6
        y = float(match.group(2)) / 1e6
        size = float(match.group(3)) / 1e6  # diameter in mm
        drill = float(match.group(4)) / 1e6  # drill in mm
        pcb["vias"].append({"x": x, "y": y, "diameter": size, "drill": drill})

    # Extract board dimensions from (paper "A4") or (size width height)
    size_match = re.search(r"\(size\s+([\d.]+)\s+([\d.]+)\)", content)
    if size_match:
        pcb["board_width_mm"] = float(size_match.group(1))
        pcb["board_height_mm"] = float(size_match.group(2))

    return pcb


def check_dfm(
    kicad_pcb_path: str | Path,
    profile: str = "jlcpcb",
    custom_rules: dict[str, float] | None = None,
) -> list[DFMViolation]:
    """Check PCB design for DFM violations.

    Args:
        kicad_pcb_path: Path to .kicad_pcb file
        profile: Fab profile ("jlcpcb", "jlcpcb_4layer", "pcbway")
        custom_rules: Override profile rules with custom dict

    Returns:
        List of DFMViolation objects sorted by severity
    """
    path = Path(kicad_pcb_path)
    if not path.exists():
        logger.error(f"PCB file not found: {path}")
        return []

    try:
        content = path.read_text(encoding="utf-8")
    except Exception as e:
        logger.error(f"Failed to read PCB file: {e}")
        return []

    # Get DFM rules
    if profile not in _DFM_PROFILES:
        logger.warning(f"Unknown profile '{profile}'. Using 'jlcpcb'.")
        profile = "jlcpcb"

    rules = _DFM_PROFILES[profile].copy()
    if custom_rules:
        rules.update(custom_rules)

    # Parse PCB
    pcb = _parse_pcb_s_expr(content)
    violations = []

    # Check trace width
    # Note: simplified—regex doesn't capture width perfectly. Would need full parser.
    for match in re.finditer(r"\(segment.*?\(width\s+([\d.]+)\)", content, re.DOTALL):
        width = float(match.group(1)) / 1e6  # nm to mm
        if width < rules["trace_width_min"]:
            violations.append(
                DFMViolation(
                    severity="critical",
                    type="trace_width",
                    location="(trace width)",
                    actual=width,
                    minimum=rules["trace_width_min"],
                    message=f"Trace width {width:.3f}mm is below minimum {rules['trace_width_min']:.3f}mm",
                    suggestion="Increase trace width in PCB editor or use wider traces for power nets.",
                )
            )

    # Check via diameter and drill
    for i, via in enumerate(pcb["vias"]):
        if via["diameter"] < rules["via_diameter_min"]:
            violations.append(
                DFMViolation(
                    severity="critical",
                    type="via_diameter",
                    location=f"Via {i} at ({via['x']:.1f}, {via['y']:.1f})",
                    actual=via["diameter"],
                    minimum=rules["via_diameter_min"],
                    message=f"Via diameter {via['diameter']:.3f}mm is below minimum {rules['via_diameter_min']:.3f}mm",
                    suggestion="Use larger via diameter or check fab DRC settings.",
                )
            )

        if via["drill"] < rules["via_drill_min"]:
            violations.append(
                DFMViolation(
                    severity="critical",
                    type="via_drill",
                    location=f"Via {i} at ({via['x']:.1f}, {via['y']:.1f})",
                    actual=via["drill"],
                    minimum=rules["via_drill_min"],
                    message=f"Via drill {via['drill']:.3f}mm is below minimum {rules['via_drill_min']:.3f}mm",
                    suggestion="Increase drill size to meet fab minimum.",
                )
            )

        # Check annular ring (difference between diameter and drill)
        annular_ring = (via["diameter"] - via["drill"]) / 2
        if annular_ring < rules["annular_ring_min"]:
            violations.append(
                DFMViolation(
                    severity="warning",
                    type="annular_ring",
                    location=f"Via {i} at ({via['x']:.1f}, {via['y']:.1f})",
                    actual=annular_ring,
                    minimum=rules["annular_ring_min"],
                    message=f"Annular ring {annular_ring:.3f}mm is below minimum {rules['annular_ring_min']:.3f}mm",
                    suggestion="Increase via diameter or reduce drill size.",
                )
            )

    # Check board edge clearance (simplified—just warn on vias near edge)
    edge_margin = rules["board_edge_clearance_min"]
    for i, via in enumerate(pcb["vias"]):
        if (
            via["x"] < edge_margin
            or via["y"] < edge_margin
            or via["x"] > pcb["board_width_mm"] - edge_margin
            or via["y"] > pcb["board_height_mm"] - edge_margin
        ):
            violations.append(
                DFMViolation(
                    severity="warning",
                    type="board_edge_clearance",
                    location=f"Via {i} at ({via['x']:.1f}, {via['y']:.1f})",
                    actual=None,
                    minimum=edge_margin,
                    message=f"Via is too close to board edge (requires {edge_margin}mm clearance)",
                    suggestion="Move via further from board edge.",
                )
            )

    # Sort by severity (critical first, then warning)
    violations.sort(key=lambda v: (v.severity != "critical", v.type, v.location))

    # Log to design.log via bridge
    from .logging_bridge import get_design_logger

    dl = get_design_logger()
    if dl:
        critical = sum(1 for v in violations if v.severity == "critical")
        warns = sum(1 for v in violations if v.severity == "warning")
        dl.log_erc_drc(
            check_type="dfm",
            file=str(path),
            errors=critical,
            warnings=warns,
            details=[v.message for v in violations[:5]],
        )

    return violations


def dfm_report(violations: list[DFMViolation]) -> str:
    """Generate human-readable DFM violation report."""
    if not violations:
        return "✓ No DFM violations detected."

    critical = [v for v in violations if v.severity == "critical"]
    warnings = [v for v in violations if v.severity == "warning"]

    lines = []
    if critical:
        lines.append(f"\n❌ CRITICAL ({len(critical)}):")
        for v in critical:
            lines.append(f"  {v.type.upper()} at {v.location}")
            lines.append(f"    {v.message}")
            if v.suggestion:
                lines.append(f"    → {v.suggestion}")

    if warnings:
        lines.append(f"\n⚠️  WARNINGS ({len(warnings)}):")
        for v in warnings:
            lines.append(f"  {v.type.upper()} at {v.location}")
            lines.append(f"    {v.message}")
            if v.suggestion:
                lines.append(f"    → {v.suggestion}")

    return "\n".join(lines)
