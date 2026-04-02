"""Subcircuit template base class and value calculators.

SubcircuitTemplate is the abstract base for all circuit block templates.
Each template takes design parameters and produces a SubcircuitResult
containing ComponentDefs, local wire segments, and boundary labels.

Value calculators snap computed resistor/capacitor values to standard
E-series and provide common EE equations (feedback dividers, filters, etc.).
"""

from __future__ import annotations

import math
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from ..component_db import ComponentDef

# ================================================================
# E-series standard resistor/capacitor values
# ================================================================

# E24 (5% tolerance) — 24 values per decade
E24_VALUES = [
    1.0,
    1.1,
    1.2,
    1.3,
    1.5,
    1.6,
    1.8,
    2.0,
    2.2,
    2.4,
    2.7,
    3.0,
    3.3,
    3.6,
    3.9,
    4.3,
    4.7,
    5.1,
    5.6,
    6.2,
    6.8,
    7.5,
    8.2,
    9.1,
]

# E96 (1% tolerance) — 96 values per decade
E96_VALUES = [
    1.00,
    1.02,
    1.05,
    1.07,
    1.10,
    1.13,
    1.15,
    1.18,
    1.21,
    1.24,
    1.27,
    1.30,
    1.33,
    1.37,
    1.40,
    1.43,
    1.47,
    1.50,
    1.54,
    1.58,
    1.62,
    1.65,
    1.69,
    1.74,
    1.78,
    1.82,
    1.87,
    1.91,
    1.96,
    2.00,
    2.05,
    2.10,
    2.15,
    2.21,
    2.26,
    2.32,
    2.37,
    2.43,
    2.49,
    2.55,
    2.61,
    2.67,
    2.74,
    2.80,
    2.87,
    2.94,
    3.01,
    3.09,
    3.16,
    3.24,
    3.32,
    3.40,
    3.48,
    3.57,
    3.65,
    3.74,
    3.83,
    3.92,
    4.02,
    4.12,
    4.22,
    4.32,
    4.42,
    4.53,
    4.64,
    4.75,
    4.87,
    4.99,
    5.11,
    5.23,
    5.36,
    5.49,
    5.62,
    5.76,
    5.90,
    6.04,
    6.19,
    6.34,
    6.49,
    6.65,
    6.81,
    6.98,
    7.15,
    7.32,
    7.50,
    7.68,
    7.87,
    8.06,
    8.25,
    8.45,
    8.66,
    8.87,
    9.09,
    9.31,
    9.53,
    9.76,
]

# Standard capacitor values (common subset across all series)
CAP_STANDARD = [
    1.0,
    1.5,
    2.2,
    3.3,
    4.7,
    6.8,
    10,
    15,
    22,
    33,
    47,
    68,
    100,
    150,
    220,
    330,
    470,
    680,
]

# Standard inductor values (common)
IND_STANDARD = [
    1.0,
    1.2,
    1.5,
    1.8,
    2.2,
    2.7,
    3.3,
    3.9,
    4.7,
    5.6,
    6.8,
    8.2,
    10,
    12,
    15,
    18,
    22,
    27,
    33,
    39,
    47,
    56,
    68,
    82,
    100,
    120,
    150,
    180,
    220,
]


def _snap_to_series(value: float, series: list[float]) -> float:
    """Snap a value to the nearest standard series value across all decades."""
    if value <= 0:
        return series[0]

    decade = 10 ** math.floor(math.log10(value))
    normalized = value / decade

    best = None
    best_dist = float("inf")
    # Check current decade and one above (to handle 9.76 -> 10.0 boundary)
    for mult in [1.0, 10.0, 0.1]:
        for sv in series:
            candidate = sv * mult
            dist = abs(math.log(candidate / normalized)) if candidate > 0 else float("inf")
            if dist < best_dist:
                best_dist = dist
                best = candidate
    return round(best * decade, 6) if best else value


def snap_to_e96(value: float) -> float:
    """Snap a resistance value to the nearest E96 standard value."""
    return _snap_to_series(value, E96_VALUES)


def snap_to_e24(value: float) -> float:
    """Snap a resistance value to the nearest E24 standard value."""
    return _snap_to_series(value, E24_VALUES)


def snap_cap(value_f: float) -> float:
    """Snap a capacitance (in Farads) to nearest standard capacitor value."""
    if value_f <= 0:
        return 1e-9
    # Normalize to pF range for comparison
    pf = value_f * 1e12
    return _snap_to_series(pf, CAP_STANDARD) * 1e-12


def snap_ind(value_h: float) -> float:
    """Snap an inductance (in Henries) to nearest standard inductor value."""
    if value_h <= 0:
        return 1e-6
    uh = value_h * 1e6
    return _snap_to_series(uh, IND_STANDARD) * 1e-6


def format_resistance(ohms: float) -> str:
    """Format resistance for schematic display: 100 -> '100R', 10000 -> '10k', etc."""
    if ohms >= 1e6:
        v = ohms / 1e6
        return f"{v:g}M" if v != int(v) else f"{int(v)}M"
    if ohms >= 1e3:
        v = ohms / 1e3
        return f"{v:g}k" if v != int(v) else f"{int(v)}k"
    v = ohms
    return f"{v:g}R" if v != int(v) else f"{int(v)}R"


def format_capacitance(farads: float) -> str:
    """Format capacitance for schematic display: 1e-9 -> '1nF', 1e-6 -> '1uF', etc."""
    if farads >= 1e-3:
        return f"{farads * 1e3:g}mF"
    if farads >= 1e-6:
        return f"{farads * 1e6:g}uF"
    if farads >= 1e-9:
        return f"{farads * 1e9:g}nF"
    return f"{farads * 1e12:g}pF"


def format_inductance(henries: float) -> str:
    """Format inductance for schematic display."""
    if henries >= 1e-3:
        return f"{henries * 1e3:g}mH"
    if henries >= 1e-6:
        return f"{henries * 1e6:g}uH"
    return f"{henries * 1e9:g}nH"


# ================================================================
# Common EE calculations
# ================================================================


def feedback_divider_top(vout: float, vref: float, r_bottom: float) -> float:
    """Calculate top feedback resistor: R_top = R_bottom * (Vout/Vref - 1)."""
    if vref <= 0 or r_bottom <= 0:
        raise ValueError(f"Invalid Vref={vref} or R_bottom={r_bottom}")
    return r_bottom * (vout / vref - 1.0)


def feedback_divider_vout(r_top: float, r_bottom: float, vref: float) -> float:
    """Calculate output voltage from feedback divider: Vout = Vref * (1 + R_top/R_bottom)."""
    if r_bottom <= 0:
        raise ValueError(f"Invalid R_bottom={r_bottom}")
    return vref * (1.0 + r_top / r_bottom)


def buck_inductor(
    vin: float, vout: float, fsw: float, iout: float, ripple_ratio: float = 0.3
) -> float:
    """Calculate buck converter inductor value for target ripple ratio.

    L = (Vin - Vout) * D / (fsw * delta_IL)
    where D = Vout/Vin, delta_IL = ripple_ratio * Iout
    """
    d = vout / vin
    delta_il = ripple_ratio * iout
    if delta_il <= 0 or fsw <= 0:
        return 2.2e-6  # default 2.2uH
    return (vin - vout) * d / (fsw * delta_il)


def buck_output_cap(delta_il: float, fsw: float, delta_vout: float = 0.020) -> float:
    """Calculate minimum output capacitance for target voltage ripple.

    Cout >= delta_IL / (8 * fsw * delta_Vout)
    """
    if fsw <= 0 or delta_vout <= 0:
        return 22e-6  # default 22uF
    return delta_il / (8.0 * fsw * delta_vout)


def crystal_load_caps(cl_spec: float, c_stray: float = 4e-12) -> float:
    """Calculate external load capacitors for a crystal.

    CL_ext = 2 * CL_spec - Cstray (each cap)
    """
    return max(1e-12, 2.0 * cl_spec - c_stray)


def rc_filter_cutoff(r: float, c: float) -> float:
    """RC low-pass filter cutoff frequency: fc = 1 / (2*pi*R*C)."""
    if r <= 0 or c <= 0:
        return 0.0
    return 1.0 / (2.0 * math.pi * r * c)


# ================================================================
# Standard footprints
# ================================================================

FP_0402C = "Capacitor_SMD:C_0402_1005Metric"
FP_0603C = "Capacitor_SMD:C_0603_1608Metric"
FP_0805C = "Capacitor_SMD:C_0805_2012Metric"
FP_1206C = "Capacitor_SMD:C_1206_3216Metric"
FP_0402R = "Resistor_SMD:R_0402_1005Metric"
FP_0603R = "Resistor_SMD:R_0603_1608Metric"
FP_0805L = "Inductor_SMD:L_0805_2012Metric"
FP_1210L = "Inductor_SMD:L_1210_3225Metric"


def cap_footprint(farads: float) -> str:
    """Pick capacitor footprint by value: small caps -> 0402, bulk -> 0805/1206."""
    if farads <= 100e-9:
        return FP_0402C
    if farads <= 10e-6:
        return FP_0805C
    return FP_1206C


def res_footprint(ohms: float, power_w: float = 0.0625) -> str:
    """Pick resistor footprint: default 0402, larger for high power."""
    if power_w > 0.125:
        return FP_0805C.replace("C_", "R_").replace("Capacitor", "Resistor")
    return FP_0402R


def ind_footprint(henries: float, current_a: float = 1.0) -> str:
    """Pick inductor footprint by current rating."""
    if current_a > 2.0:
        return FP_1210L
    return FP_0805L


# ================================================================
# Subcircuit result
# ================================================================


@dataclass
class LocalWire:
    """A wire segment within a subcircuit (explicit routing, not label-only)."""

    x1: float
    y1: float
    x2: float
    y2: float


@dataclass
class BoundaryPort:
    """A named port at the subcircuit boundary (becomes a global label)."""

    name: str  # net name
    direction: str = "bidirectional"  # bidirectional, input, output, passive


@dataclass
class SubcircuitResult:
    """Output of a subcircuit template — everything needed to place it on a sheet."""

    components: list[ComponentDef] = field(default_factory=list)
    local_wires: list[LocalWire] = field(default_factory=list)
    boundary_ports: list[BoundaryPort] = field(default_factory=list)
    annotations: list[str] = field(default_factory=list)
    # The primary IC (first component) — used for sheet allocation
    primary_category: str = "power"


# ================================================================
# Template base class
# ================================================================


class SubcircuitTemplate(ABC):
    """Abstract base for subcircuit templates.

    Subclasses implement `generate()` which takes design parameters
    and returns a SubcircuitResult with components, wires, and ports.
    """

    # Metadata for registry
    template_type: str = ""  # "buck", "ldo", "usb_controller", etc.
    description: str = ""
    param_schema: list[dict[str, Any]] = []

    @abstractmethod
    def generate(self, params: dict[str, Any]) -> SubcircuitResult:
        """Generate subcircuit from design parameters.

        Params dict is template-specific. Common keys:
          - ref_prefix: str — base ref designator (e.g., "U12")
          - vin: float — input voltage
          - vout: float — output voltage
          - iout: float — output current
          - ic: str — specific IC MPN (optional, template may have default)
        """

    def validate_params(self, params: dict[str, Any]) -> list[str]:
        """Return list of error messages for invalid params. Empty = valid."""
        return []

    def get_param_schema(self) -> list[dict[str, Any]]:
        """Return a copy of the template's declared parameter schema."""
        return [dict(item) for item in getattr(self, "param_schema", [])]


# ================================================================
# Template registry
# ================================================================


class SubcircuitRegistry:
    """Registry of available subcircuit templates, queryable by type name."""

    def __init__(self):
        self._templates: dict[str, SubcircuitTemplate] = {}

    def register(self, template: SubcircuitTemplate):
        """Register a template by its type name."""
        self._templates[template.template_type] = template

    def get(self, type_name: str) -> SubcircuitTemplate | None:
        """Look up a template by type name (e.g., 'buck', 'ldo')."""
        return self._templates.get(type_name)

    def available_types(self) -> list[str]:
        """List all registered template type names."""
        return sorted(self._templates.keys())

    def __len__(self):
        return len(self._templates)


# ================================================================
# Built-in registry with standard templates
# ================================================================


def _build_default_registry() -> SubcircuitRegistry:
    """Build registry with all built-in subcircuit templates."""
    reg = SubcircuitRegistry()
    # Import here to avoid circular imports
    from .buck import BuckConverterTemplate
    from .clock import ClockSynthTemplate
    from .ethernet import EthernetPHYTemplate
    from .ldo import LDOTemplate
    from .usb import USBControllerTemplate, USBHubTemplate

    reg.register(BuckConverterTemplate())
    reg.register(ClockSynthTemplate())
    reg.register(EthernetPHYTemplate())
    reg.register(LDOTemplate())
    reg.register(USBControllerTemplate())
    reg.register(USBHubTemplate())
    return reg


DEFAULT_REGISTRY = None


def get_default_registry() -> SubcircuitRegistry:
    """Get the default subcircuit registry (lazy-loaded)."""
    global DEFAULT_REGISTRY
    if DEFAULT_REGISTRY is None:
        DEFAULT_REGISTRY = _build_default_registry()
    return DEFAULT_REGISTRY
