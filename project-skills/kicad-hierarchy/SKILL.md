---
name: kicad-hierarchy
description: Design and verify professional multi-sheet KiCad hierarchies generated from Circuit Weaver functional sections. Use when adding, splitting, renaming, or reviewing schematic sheets, cross-sheet interfaces, root symbols, sheet ownership, or final hierarchy ERC.
---

# KiCad Hierarchy

Treat the design spec as the source of truth. Do not hand-build or patch a root
schematic with an assumed repository script.

## Define functional ownership

Give every architectural block a stable unique `id` and explicit `section`:

```yaml
blocks:
  - id: input-protection
    section: power_input
    kind: template
    type: protection
    ref: D1
    params:
      protect_net: VIN

  - id: system-regulator
    section: power_regulation
    kind: template
    type: buck
    ref: U2
    params:
      vin: 12
      vout: 3.3
      iout: 1.0

  - id: main-controller
    section: core_processing
    kind: template
    type: wireless_module
    ref: U3

  - id: external-connectors
    section: external_io
    kind: template
    type: usb_c_connector
    ref: J1
```

Use one section per major functional responsibility: input protection, each
power stage, processing, sensors/analog front end, communications, external
I/O, user interface, and debug/test. Do not collapse unrelated sections to
save files. Generated decoupling, straps, pull-ups, and other support parts
remain with their owning block.

## Generate transactionally

```bash
circuit-weaver generate "${SPEC_PATH}" \
  --output "${OUTPUT_DIR}" \
  --require-kicad
```

Generation sanitizes and disambiguates sheet names, partitions oversized
sheets, creates the root hierarchy, and publishes all files atomically. Read
`root_schematic` and every child `artifact` from `artifact_manifest.json`;
never guess sheet filenames or assume `main.kicad_sch`.

`--require-kicad` is the final release-quality gate. Internal validation is
not a substitute for loading the exact final hierarchy in real KiCad and
running ERC.

## Review the hierarchy

- [ ] Every major function has a distinct, descriptive sheet.
- [ ] Every referenced child file exists once and no sanitized names collide.
- [ ] Stable block ownership is visible in the expected sheet.
- [ ] Generated support passives remain beside their owning circuit.
- [ ] Root sheet symbols link to the correct child files.
- [ ] Hierarchical pins/labels agree in name and direction.
- [ ] Cross-sheet power and signal connectivity matches the design interfaces.
- [ ] No unrelated sheet-local wires or labels merge nets by coordinate/name.
- [ ] Page titles, sheet names, notes, and paper sizes remain readable.
- [ ] `artifact_manifest.json` says `kicad_verified: true` and
      `verification_status: verified` for a release-quality claim.

After review, open the manifest-selected root in KiCad and run **Update PCB
from Schematic**. Never route or manufacture from schematic review artifacts.
