---
name: kicad_pinmap
description: >
  Pin-to-net mapping auditor -- verifies that every IC pin in the schematic
  is connected to the correct net, matched against a pin map source of truth
  (CSV, datasheet table, or Python dict). Critical for BGA/QFN devices where
  swap errors are invisible to DRC/ERC.
---

## Why This Matters

ERC and DRC cannot catch a swapped pin. A power pin on a signal net passes all
automated checks but produces a dead or damaged board. The only defense is
comparing the schematic pin-to-net assignment against the datasheet pinout table.

## Pin Map Source Format

```python
# scripts/pin_maps.py
DEVICE_PINMAP = {
    "A1":  "GND",
    "A2":  "VDD_1V8",
    "A3":  "SPI_CLK",
    "B1":  "RESET_N",
    "C4":  "__NC__",   # explicitly no-connect
}
```

Sources (in priority order):
1. Datasheet pin function table
2. Reference design / eval board schematic
3. Manufacturer application note

## Audit Workflow

```
1. Extract pin-net mapping from schematic:
   analyze_schematic.py -> nets section -> per-component pin list

2. Compare against expected pin map:
   scripts/audit_pinmap.py <ref> analysis.json pin_maps.py

3. For each mismatch: investigate (may be intentional renaming or a bug)

4. For each unmapped pin: decide connected/no-connect, update pin_maps.py

5. Regenerate schematic to apply corrected mappings
```

## Gap Filling

Unmapped pins should get no-connect markers rather than floating unconnected.
Floating digital inputs can cause latch-up or undefined behavior.

## Coverage Targets

Flag any IC below 80% mapped. No-connect pins count as mapped.

| IC ref | Package | Total pins | Mapped | NC | Coverage |
|-|-|-|-|-|-|
| (fill in) | | | | | |

## Common Pitfalls

**SOT-23 transistors:** BCE, BEC, EBC, and CBE orderings all exist for NPN BJTs;
GDS, GSD, SGD for N-MOSFETs. The KiCad symbol `lib_id` suffix encodes an assumed
pinout. Verify against the actual MPN's datasheet -- especially when no MPN is set.

**Multi-unit ICs:** Op-amp and gate packages with a shared VCC/GND unit.
Ensure the power unit is placed and connected -- a missing power unit causes an
ERC warning that can be overlooked.

**Active-low signals:** Verify RESET_N, CS_N, OE_N are driven with the correct
polarity. A high-true signal on an active-low input means always-asserted.
