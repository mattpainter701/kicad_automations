# Design IR Schema

The Design Intermediate Representation (IR) is the canonical internal format that Circuit Weaver uses to represent a hardware design. It is compiled from the user-facing YAML spec and consumed by the validator, generator, and diff engine.

## YAML Spec → Design IR

```
user YAML spec → normalize → compile → DesignIR
                                          ├─ metadata
                                          ├─ blocks[]
                                          ├─ interfaces[]
                                          ├─ approved_overrides[]
                                          └─ pcb_constraints[]
```

## Top-Level Structure

```yaml
# User-facing YAML spec (input format)
project: "my-design"
version: "1.0"
author: "Engineer Name"

power:
  - section: power
    template: buck
    ref: U1
    ic: AP62300
    params:
      vout: 3.3
      iout_max: 1.2

digital:
  - section: digital
    template: mcu
    ref: U2
    ic: STM32G030F6P6
    params:
      speed_mhz: 64

interfaces:
  - block_id: U1
    name: VOUT
    direction: output
    description: "3.3V regulated supply"

approved_overrides:
  - ref: R1
    field: value
    old: "10k"
    new: "4.7k"
    reason: "Adjusted feedback divider for 3.3V output"

pcb_constraints:
  - type: placement
    ref: C1
    constraint: "within 3mm of U1 pin 5"
```

## DesignIR Dataclass

```python
@dataclass
class DesignIR:
    metadata: dict[str, Any]
    # {"project": str, "version": str, "author": str, ...}

    blocks: list[DesignBlock]
    # Each circuit block (IC + its support passives)

    interfaces: list[DesignInterface]
    # Cross-block connections and boundary ports

    approved_overrides: list[dict[str, Any]]
    # PCB-feedback-approved component substitutions

    pcb_constraints: list[dict[str, Any]]
    # Layout constraints fed back from PCB review
```

## DesignBlock

Each block represents one subcircuit — an IC and its surrounding passives.

```python
@dataclass
class DesignBlock:
    id: str                    # Unique block identifier
    section: str               # Grouping: "power", "digital", "analog", "comms"
    kind: str                  # "template" (from library) or "component" (raw part)
    ref: str                   # Reference designator (e.g., "U1")
    template_type: str         # Template name (e.g., "buck", "ldo", "i2c_bus")
    ic: str                    # IC MPN (e.g., "AP62300")
    params: dict[str, Any]     # Template parameters (vout, iout_max, etc.)
    value: str                 # Component value (for raw components)
    description: str           # Human-readable description
    mpn: str                   # Manufacturer part number
    required_support: dict     # Support passive requirements
    part_bindings: dict        # Bound part selections
    presentation_group: str    # Schematic grouping hint
    interfaces: list[DesignInterface]  # Block's boundary ports
```

### Block `params` (template-specific)

Parameters vary by template. See [docs/templates.md](templates.md) for per-template parameter schemas. Common parameters:

| Parameter | Type | Description |
|-|-|-|
| `vout` | float | Output voltage (regulators) |
| `vin_min` / `vin_max` | float | Input voltage range |
| `iout_max` | float | Maximum output current (A) |
| `fsw` | float | Switching frequency (Hz) |
| `speed_khz` | int | Bus speed (I2C/SPI) |
| `bus_capacitance_pf` | float | Bus capacitance for pull-up calculation |

## DesignInterface

Interfaces define connections between blocks or to the outside world.

```python
@dataclass
class DesignInterface:
    block_id: str        # Which block owns this interface
    name: str            # Interface name (e.g., "VOUT", "SDA", "GND")
    direction: str       # "input", "output", "bidirectional", "passive"
    description: str     # Human-readable description
```

## Approved Overrides

Component substitutions accepted from PCB feedback:

```yaml
approved_overrides:
  - ref: "R1"           # Reference designator
    field: "value"       # Field being overridden
    old: "10k"          # Original value
    new: "4.7k"         # Approved replacement
    reason: "..."       # Justification
```

## PCB Constraints

Layout constraints fed back from PCB review:

```yaml
pcb_constraints:
  - type: "placement"          # placement | routing | clearance
    ref: "C1"                  # Component reference
    constraint: "within 3mm of U1 pin 5"
  - type: "routing"
    net: "VBUS"
    constraint: "minimum 0.5mm trace width"
```

## Compilation

The YAML spec is compiled to Design IR by `compile_design_ir()`:

1. **Normalize** — standardize field names, resolve aliases
2. **Resolve components** — look up ICs in registry → KiCad lib → JSON DB → EasyEDA
3. **Expand templates** — each block's template generates support passives
4. **Build interfaces** — extract boundary ports from block definitions
5. **Carry overrides** — merge `approved_overrides` and `pcb_constraints`

The resulting `DesignIR` is consumed by:
- `validate_design()` — runs the 10-check validation pipeline
- `generate_artifacts()` — produces KiCad schematic files
- `diff_designs()` — compares two IR instances structurally
