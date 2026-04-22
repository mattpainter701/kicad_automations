# IC Data System

The IC data system separates component-specific knowledge (pin maps, electrical specs) from circuit topology logic (feedback dividers, inductor sizing). This lets agents add support for new ICs by writing JSON entries — no Python code changes needed.

## Architecture

```
┌──────────────────────────────────────────────────────┐
│ YAML Design Spec                                      │
│   type: buck, ic: AP62300, vin: 12, vout: 3.3        │
└───────────────┬──────────────────────────────────────┘
                │
    ┌───────────▼───────────┐
    │ SubcircuitRegistry    │
    │  1. Legacy template?  │──yes──▶ BuckConverterTemplate.generate()
    │  2. JSON IC data?     │──yes──▶ DataDrivenTemplate
    │  3. Not found         │            │
    └───────────────────────┘            ▼
                              ┌──────────────────────┐
                              │ Topology Builder      │
                              │  build_switching_     │
                              │  regulator(ic_data,   │
                              │  params)              │
                              └──────────┬───────────┘
                                         │
                              ┌──────────▼───────────┐
                              │ EE Calculations       │
                              │  feedback_divider()   │
                              │  buck_inductor()      │
                              │  snap_to_e96()        │
                              └──────────┬───────────┘
                                         │
                              ┌──────────▼───────────┐
                              │ SubcircuitResult      │
                              │  ComponentDef + ports │
                              └──────────────────────┘
```

## IC Data Store

**Location:** `src/circuit_weaver/ic_data/`

IC application data is stored in JSON files, grouped by function:

| File | Contents | ICs |
|------|----------|-----|
| `switching_regulator.json` | Buck, boost, buck-boost converters | AP62300, TPS62088, TPS61230A, ... |
| `linear_regulator.json` | LDOs, charge pumps, voltage refs, chargers | TLV75518, AMS1117, REF3030, ... |
| `amplifier.json` | Op-amps, instrumentation amps, audio amps | LM358, INA128PA, PAM8302A, ... |
| `bus_interface.json` | I2C, SPI, CAN, RS-485, level shifters | SN65HVD230, PCA9306, ... |
| `converter.json` | ADCs, DACs, current sense | ADS1115, MCP4725, INA219, ... |
| `oscillator.json` | Crystals, clock synthesizers | ABM8G, AD9528, ... |
| `protection.json` | TVS, ESD diodes | SMBJ5.0A, PESD5V0S1BA, ... |
| `connector.json` | USB-C, barrel jack, JST, pin headers | USB4125-GF-A, BARREL_JACK, ... |
| `memory.json` | EEPROM, SPI flash | 24LC256, AT25SF128A |
| `misc.json` | RTC, display, motor, wireless, etc. | DS3231, SSD1306, DRV8833, ... |
| `custom.json` | Agent-populated entries (starts empty) | — |

### JSON Entry Format

```json
{
  "AP62300": {
    "topology": "buck",
    "description": "3A Sync Buck Regulator SOT-23-6",
    "footprint": "SOT-23-6",
    "vref": 0.8,
    "fsw": 600000,
    "iout_max": 3.0,
    "r_fbb_default": 100000,
    "pins": [
      {"number": "1", "name": "GND", "type": "power_in", "side": "B"},
      {"number": "2", "name": "SW", "type": "output", "side": "T"},
      {"number": "3", "name": "VIN", "type": "power_in", "side": "L"},
      {"number": "4", "name": "FB", "type": "input", "side": "R"},
      {"number": "5", "name": "EN", "type": "input", "side": "L"},
      {"number": "6", "name": "BST", "type": "passive", "side": "T"}
    ],
    "pin_vin": "3",
    "pin_gnd": "1",
    "pin_sw": "2",
    "pin_fb": "4",
    "pin_en": "5",
    "pin_bst": "6"
  }
}
```

### Required Fields

- `topology` — which builder function handles this IC (e.g., `"buck"`, `"ldo"`, `"opamp"`)
- `pins` — array of pin definitions with number, name, electrical type, and symbol side
- `pin_*` or `pin_roles` — maps functional roles to pin numbers

### Topology-Specific Fields

**Switching regulators** (`buck`, `boost`, `buck_boost`):
- `vref` — feedback reference voltage (V)
- `fsw` — switching frequency (Hz)
- `r_fbb_default` — default bottom feedback resistor (Ω)
- `pin_vin`, `pin_gnd`, `pin_sw`, `pin_fb`, `pin_en`, `pin_bst`

**Linear regulators** (`ldo`):
- `vout_fixed` — fixed output voltage (V), if applicable
- `vdropout` — dropout voltage (V)
- `iq_ua` — quiescent current (µA)
- `cin`, `cout` — recommended cap values (F)
- `pin_vin`, `pin_gnd`, `pin_out`, `pin_en`

## Python API

```python
from circuit_weaver.ic_data import get_ic_data, register_ic, get_all_ics

# Look up an IC
ic = get_ic_data("AP62300")  # returns dict or None

# List all ICs of a topology
bucks = get_all_ics("buck")  # {"AP62300": {...}, "TPS62088": {...}}

# Add a new IC at runtime (agent workflow)
register_ic("MY_NEW_LDO", {
    "topology": "ldo",
    "description": "Custom 3.3V LDO",
    "footprint": "SOT-23-5",
    "vout_fixed": 3.3,
    "vdropout": 0.2,
    "iout_max": 0.5,
    "cin": 1e-6,
    "cout": 1e-6,
    "pins": [...],
    "pin_vin": "1", "pin_gnd": "2", "pin_out": "3",
})
# Now `type: ldo, ic: MY_NEW_LDO` works in design YAML
```

## Topology Builders

**Location:** `src/circuit_weaver/subcircuits/topology_builders.py`

Each builder takes IC data (from JSON) and design parameters, then produces
a `SubcircuitResult` — the same output as legacy template classes.

| Builder | Topologies | Key Calculations |
|---------|-----------|-----------------|
| `build_switching_regulator` | buck, boost, buck_boost | Feedback divider, inductor sizing, output cap |
| `build_linear_regulator` | ldo | Dropout/thermal checks, cap sizing |
| `build_generic` | all others | Pin assignment + standard decoupling |

All EE calculation functions are in `subcircuits/base.py` and are reused by both legacy templates and data-driven builders.

## Resolution Order

When the registry looks up a template type (e.g., `"buck"`):

1. **Legacy template class** — if a Python `BuckConverterTemplate` is registered, use it
2. **JSON IC data** — if JSON files contain ICs with `topology: "buck"`, wrap in `DataDrivenTemplate`
3. **Not found** — validation error

Legacy templates take priority, ensuring backward compatibility. The data-driven path activates for new topologies or when legacy templates are eventually removed.

## Adding Support for a New IC

### As an agent (no code changes):

```python
from circuit_weaver.ic_data import register_ic

register_ic("TPS54308", {
    "topology": "buck",
    "description": "3A Buck Converter SOT-23-8",
    "footprint": "SOT-23-8",
    "vref": 0.6,
    "fsw": 1200000,
    "r_fbb_default": 100000,
    "pins": [
        {"number": "1", "name": "BOOT", "type": "passive", "side": "T"},
        {"number": "2", "name": "VIN", "type": "power_in", "side": "L"},
        {"number": "3", "name": "EN", "type": "input", "side": "L"},
        {"number": "4", "name": "SS/TR", "type": "input", "side": "L"},
        {"number": "5", "name": "VSENSE", "type": "input", "side": "R"},
        {"number": "6", "name": "GND", "type": "power_in", "side": "B"},
        {"number": "7", "name": "PH", "type": "output", "side": "T"},
        {"number": "8", "name": "EPAD", "type": "power_in", "side": "B"}
    ],
    "pin_vin": "2", "pin_gnd": "6", "pin_sw": "7",
    "pin_fb": "5", "pin_en": "3", "pin_bst": "1",
    "pin_gnd_extra": ["8"]
}, persist=True)  # saves to custom.json
```

The IC is immediately usable in YAML specs:
```yaml
power:
  - type: buck
    ic: TPS54308
    ref: U1
    vin: 12
    vout: 3.3
    iout: 2
```
