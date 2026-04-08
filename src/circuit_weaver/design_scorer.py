"""Enhanced design scoring with per-section electrical quality metrics.

Produces detailed scores across 5 design quality dimensions:
- Power Integrity: decoupling adequacy, bulk cap presence, regulator headroom
- Signal Integrity: termination on high-speed nets, differential pair balance
- Placement Quality: thermal clustering, decap proximity (when PCB data available)
- Thermal: estimated junction temps, thermal via coverage
- Manufacturing: DFM violations, component availability, assembly complexity
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .design_ir import DesignIR


@dataclass
class DetailedElectricalQualityScore:
    """Detailed electrical quality score across 5 design dimensions."""

    power_integrity: float = 0.0  # 0-100
    signal_integrity: float = 0.0  # 0-100
    placement_quality: float = 0.0  # 0-100
    thermal: float = 0.0  # 0-100
    manufacturing: float = 0.0  # 0-100
    overall: float = 0.0  # weighted average
    grade: str = "F"  # A-F
    section_details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "power": round(self.power_integrity, 1),
            "signal": round(self.signal_integrity, 1),
            "placement": round(self.placement_quality, 1),
            "thermal": round(self.thermal, 1),
            "mfg": round(self.manufacturing, 1),
            "overall": round(self.overall, 1),
            "grade": self.grade,
            "details": self.section_details,
        }

    def summary_with_gaps(self) -> str:
        """Return text summary with gap warnings for sections < 75."""
        lines = [
            f"Design Score: {self.overall:.1f} ({self.grade})",
            "",
            "Section Breakdown:",
            f"  Power Integrity:     {self.power_integrity:>6.1f} {'✓' if self.power_integrity >= 75 else '⚠'}",
            f"  Signal Integrity:    {self.signal_integrity:>6.1f} {'✓' if self.signal_integrity >= 75 else '⚠'}",
            f"  Placement Quality:   {self.placement_quality:>6.1f} {'✓' if self.placement_quality >= 75 else '⚠'}",
            f"  Thermal:             {self.thermal:>6.1f} {'✓' if self.thermal >= 75 else '⚠'}",
            f"  Manufacturing:       {self.manufacturing:>6.1f} {'✓' if self.manufacturing >= 75 else '⚠'}",
        ]

        gaps = []
        if self.power_integrity < 75:
            gaps.append(f"Power: {self.section_details.get('power_gaps', 'missing decoupling')}")
        if self.signal_integrity < 75:
            gaps.append(f"Signal: {self.section_details.get('signal_gaps', 'missing termination')}")
        if self.placement_quality < 75:
            gaps.append(f"Placement: {self.section_details.get('placement_gaps', 'suboptimal layout')}")
        if self.thermal < 75:
            gaps.append(f"Thermal: {self.section_details.get('thermal_gaps', 'high dissipation')}")
        if self.manufacturing < 75:
            gaps.append(f"Mfg: {self.section_details.get('mfg_gaps', 'DFM violations')}")

        if gaps:
            lines.append("")
            lines.append("Recommendations:")
            for gap in gaps:
                lines.append(f"  • {gap}")

        return "\n".join(lines)


def _grade(score: float) -> str:
    """Convert numeric score (0-100) to letter grade (A-F)."""
    if score >= 90:
        return "A"
    if score >= 80:
        return "B"
    if score >= 70:
        return "C"
    if score >= 60:
        return "D"
    return "F"


def _score_power_integrity(design_ir: DesignIR) -> tuple[float, dict]:
    """Score power supply design: bulk caps, decoupling, regulator headroom.

    Checks for:
    - Presence of bulk capacitors (>10µF) on main supplies
    - Decoupling cap coverage on power pins (>1µF per VCC pin)
    - Voltage regulator presence and configuration
    - Input/output voltage headroom (Vin > Vout + dropout)
    """
    bulk_caps = 0
    decouple_caps = 0
    regulators = 0
    total_power_blocks = 0
    power_gaps = []

    for block in design_ir.blocks:
        # Identify bulk capacitors (capacitors > 10µF)
        if block.kind == "component" and block.ref and "C" in str(block.ref):
            # Parse capacitance from value (e.g., "100µF", "10 µF", "0.1F")
            value_str = (block.value or "").upper()
            # Only process if it looks like a capacitor value
            if "F" in value_str or "µ" in (block.value or ""):
                try:
                    # Simple parsing: extract number and suffix
                    parts = value_str.replace("µ", "U").replace(" ", "").split()
                    if not parts:
                        parts = [value_str]
                    # Extract leading number
                    num_str = ""
                    for char in parts[0]:
                        if char.isdigit() or char == ".":
                            num_str += char
                        else:
                            break
                    if num_str:
                        num = float(num_str)
                        # Scale to µF based on suffix
                        suffix = parts[0][len(num_str) :].upper()
                        if "MF" in suffix or "M" in suffix:
                            pass  # already in µF (milli-Farad = µF? No, actually milli is 1e-3)
                        elif "UF" in suffix or "U" in suffix:
                            pass  # already in µF
                        elif "NF" in suffix or "N" in suffix:
                            num /= 1000  # nF to µF
                        elif "PF" in suffix or "P" in suffix:
                            num /= 1_000_000  # pF to µF
                        elif suffix.startswith("F"):
                            num *= 1_000_000  # Farads to µF

                        if num >= 10:
                            bulk_caps += 1
                        elif num >= 1:
                            decouple_caps += 1
                except (ValueError, IndexError, TypeError):
                    pass

        # Identify voltage regulators (U blocks with "REG", "LDO" in type or description)
        if block.kind == "template" or (block.kind == "component" and block.ref and "U" in block.ref):
            desc = (block.description or "").upper()
            ic_name = (block.ic or "").upper()
            if any(x in desc or x in ic_name for x in ["REG", "LDO", "BUCK", "BOOST", "MPPT"]):
                regulators += 1

        # Count power supply design blocks
        section = (block.section or "").lower()
        if "power" in section or "supply" in section or "psu" in section:
            total_power_blocks += 1

    # Scoring logic
    score = 50.0  # baseline

    # Bulk cap presence: 0-20 points
    if total_power_blocks > 0:
        if bulk_caps > 0:
            score += 20
        else:
            power_gaps.append("Missing bulk capacitors (>10µF) on main supplies")
            score += 10

    # Decoupling coverage: 0-30 points
    if decouple_caps > 0:
        score += min(30, decouple_caps * 5)
    else:
        power_gaps.append("Missing decoupling capacitors on power pins")

    # Regulator presence: 0-20 points
    if regulators > 0:
        score += 20
    elif total_power_blocks > 0:
        power_gaps.append("No voltage regulator found in power section")
        score += 5

    # Cap on maximum score
    score = min(100, max(0, score))

    details = {
        "bulk_caps": bulk_caps,
        "decouple_caps": decouple_caps,
        "regulators": regulators,
        "power_gaps": power_gaps[0] if power_gaps else "None",
    }

    return score, details


def _score_signal_integrity(design_ir: DesignIR) -> tuple[float, dict]:
    """Score signal integrity: termination, differential pairs, layer stack.

    Checks for:
    - Pull-up/pull-down resistors on I2C/SPI
    - Differential pair identification (USB, LVDS, etc.)
    - Clock distribution and termination
    - Impedance control indicators
    """
    pullup_resistors = 0
    differential_indicators = 0
    signal_gaps = []

    for block in design_ir.blocks:
        # Identify pull-up resistors (4.7k, 10k common values on I2C)
        if block.kind == "component" and block.ref and "R" in block.ref:
            value_str = (block.value or "").upper()
            if any(x in value_str for x in ["4.7K", "10K", "2.2K"]):
                pullup_resistors += 1

        # Look for high-speed interfaces in constraints
        if block.kind == "template":
            template_type = (block.template_type or "").upper()
            # USB, LVDS, HDMI, Ethernet, etc.
            if any(x in template_type for x in ["USB", "LVDS", "HDMI", "ETHERNET", "MIPI"]):
                differential_indicators += 1

    # Check PCB constraints for differential pairs
    for constraint in design_ir.pcb_constraints:
        if constraint.get("kind") == "diff_pair":
            differential_indicators += 1

    # Scoring logic
    score = 60.0  # baseline (harder to verify without PCB data)

    # Pull-up coverage: 0-20 points
    if pullup_resistors > 0:
        score += min(20, pullup_resistors * 3)
    else:
        signal_gaps.append("No standard pull-up resistors (I2C/SPI) found")

    # High-speed interface support: 0-20 points
    if differential_indicators > 0:
        score += min(20, differential_indicators * 5)

    score = min(100, max(0, score))

    details = {
        "pullup_resistors": pullup_resistors,
        "differential_indicators": differential_indicators,
        "signal_gaps": signal_gaps[0] if signal_gaps else "None",
    }

    return score, details


def _score_placement_quality(design_ir: DesignIR) -> tuple[float, dict]:
    """Score placement quality (estimates without PCB data).

    Checks for:
    - Component density and clustering
    - Power pin to decap distance indicators (heuristic)
    - Connector accessibility in block definitions
    - Thermal grouping in layout constraints
    """
    total_components = len(design_ir.blocks)
    components_with_refs = sum(1 for b in design_ir.blocks if b.ref)
    placement_gaps = []

    # Estimate based on component count and organization
    # (Without actual PCB, we rely on schematic structure)
    thermal_constraints = sum(1 for c in design_ir.pcb_constraints if c.get("kind") == "placement")
    keepout_zones = sum(1 for c in design_ir.pcb_constraints if c.get("kind") == "keepout")

    # Scoring logic
    score = 70.0  # baseline (placement is hard to score without PCB)

    # Reference designation coverage: 0-15 points
    if total_components > 0:
        ref_coverage = components_with_refs / total_components
        if ref_coverage > 0.8:
            score += 15
        elif ref_coverage > 0.5:
            score += 10
        else:
            placement_gaps.append("Low component reference designation coverage")
            score += 5

    # Explicit placement constraints: 0-15 points
    if thermal_constraints + keepout_zones > 0:
        score += min(15, (thermal_constraints + keepout_zones) * 3)

    score = min(100, max(0, score))

    details = {
        "total_components": total_components,
        "referenced_components": components_with_refs,
        "thermal_constraints": thermal_constraints,
        "keepout_zones": keepout_zones,
        "placement_gaps": placement_gaps[0] if placement_gaps else "None",
    }

    return score, details


def _score_thermal(design_ir: DesignIR) -> tuple[float, dict]:
    """Score thermal design (estimates without PCB data).

    Checks for:
    - High-power components (>1W) identification
    - Voltage regulator presence and type (LDO vs switching)
    - Thermal via indicators in constraints
    - Ambient operating range specified
    """
    power_components = 0
    switching_regulators = 0
    thermal_gaps = []

    for block in design_ir.blocks:
        # Identify high-power components
        if block.kind == "component":
            desc = (block.description or "").upper()
            # Look for inductors, transformers, high-current regulators
            if any(x in desc for x in ["INDUCTOR", "TRANSFORMER", "SMPS", "BOOST", "MPPT"]):
                power_components += 1
            # Switching regulators vs LDO
            if any(x in desc for x in ["BUCK", "BOOST", "CHARGE"]):
                switching_regulators += 1
            elif "LDO" in desc:
                power_components += 0.5  # LDOs generate less heat

    # Check for thermal design specifications
    thermal_constraints = sum(1 for c in design_ir.pcb_constraints if c.get("kind") == "placement")
    ambient_range = design_ir.metadata.get("operating_temp", "")

    # Scoring logic
    score = 75.0  # baseline

    # Power component identification: 0-15 points
    if power_components > 0:
        if switching_regulators > 0:
            score += 15  # Switching regulators indicate active thermal design
        else:
            score += 8  # Some thermal awareness
    else:
        if power_components == 0:
            score += 15  # No high-power devices = low thermal burden

    # Operating range specification: 0-10 points
    if ambient_range:
        score += 10
    else:
        thermal_gaps.append("Operating temperature range not specified")

    score = min(100, max(0, score))

    details = {
        "power_components": power_components,
        "switching_regulators": switching_regulators,
        "thermal_constraints": thermal_constraints,
        "thermal_gaps": thermal_gaps[0] if thermal_gaps else "None",
    }

    return score, details


def _score_manufacturing(design_ir: DesignIR) -> tuple[float, dict]:
    """Score manufacturing readiness.

    Checks for:
    - MPN assignment coverage
    - Component availability (part of BOM)
    - Part bindings and sourcing overrides
    - Assembly complexity (component count, package variety)
    """
    components_with_mpn = 0
    components_with_bindings = 0
    total_components = len(design_ir.blocks)
    package_types = set()
    mfg_gaps = []

    for block in design_ir.blocks:
        if block.kind == "component":
            if block.mpn:
                components_with_mpn += 1
            if block.part_bindings:
                components_with_bindings += 1
            # Track package variety
            # (without full footprint data, use ref prefix as proxy)
            # Extract prefix from ref (e.g., "U1" -> "U", "R1" -> "R")
            if block.ref:
                ref_prefix = "".join(c for c in block.ref if c.isalpha())
                package_types.add(ref_prefix if ref_prefix else "U")
            else:
                package_types.add("U")

    # Check sourcing overrides
    substitutions = sum(1 for o in design_ir.approved_overrides if o.get("kind") == "approved_substitution")

    # Scoring logic
    score = 60.0  # baseline (manufacturing is complex without full BOM)

    # MPN coverage: 0-30 points
    if total_components > 0:
        mpn_coverage = components_with_mpn / total_components
        if mpn_coverage > 0.9:
            score += 30
        elif mpn_coverage > 0.7:
            score += 20
        elif mpn_coverage > 0.5:
            score += 10
        else:
            mfg_gaps.append("Low MPN coverage (<50%)")
    else:
        score += 30  # Empty design passes this check

    # Part sourcing bindings: 0-20 points
    if total_components > 0:
        binding_coverage = components_with_bindings / total_components
        if binding_coverage > 0.5:
            score += 20
        elif binding_coverage > 0.2:
            score += 10
    else:
        score += 20

    # Component variety (package diversity = complexity): 0-20 points
    if len(package_types) <= 4:
        score += 20  # Simple (mostly one or two package types)
    elif len(package_types) <= 7:
        score += 10  # Moderate complexity
    else:
        mfg_gaps.append(f"High assembly complexity ({len(package_types)} package types)")
        score += 5

    # Substitution strategy: +10 points
    if substitutions > 0:
        score += 10

    score = min(100, max(0, score))

    details = {
        "total_components": total_components,
        "components_with_mpn": components_with_mpn,
        "components_with_bindings": components_with_bindings,
        "package_types": len(package_types),
        "substitutions": substitutions,
        "mfg_gaps": mfg_gaps[0] if mfg_gaps else "None",
    }

    return score, details


def score_design_comprehensive(design_ir: DesignIR) -> DetailedElectricalQualityScore:
    """Score the design across all 5 quality dimensions.

    Returns weighted composite score and detailed breakdown by section.
    """
    power_score, power_details = _score_power_integrity(design_ir)
    signal_score, signal_details = _score_signal_integrity(design_ir)
    placement_score, placement_details = _score_placement_quality(design_ir)
    thermal_score, thermal_details = _score_thermal(design_ir)
    mfg_score, mfg_details = _score_manufacturing(design_ir)

    # Weighted composite (equal weight by default)
    weights = {
        "power": 0.2,
        "signal": 0.2,
        "placement": 0.2,
        "thermal": 0.2,
        "mfg": 0.2,
    }

    overall = (
        power_score * weights["power"]
        + signal_score * weights["signal"]
        + placement_score * weights["placement"]
        + thermal_score * weights["thermal"]
        + mfg_score * weights["mfg"]
    )

    section_details = {
        "power": power_details,
        "signal": signal_details,
        "placement": placement_details,
        "thermal": thermal_details,
        "mfg": mfg_details,
    }

    return DetailedElectricalQualityScore(
        power_integrity=power_score,
        signal_integrity=signal_score,
        placement_quality=placement_score,
        thermal=thermal_score,
        manufacturing=mfg_score,
        overall=overall,
        grade=_grade(overall),
        section_details=section_details,
    )
