---
name: kicad-pcb-place
description: Review Circuit Weaver's exhaustive placement proposal and apply approved SVG coordinates to a real electrically annotated KiCad PCB. Use after schematic generation for placement optimization, official-reference review, interactive SVG editing, strict reference reconciliation, and PCB placement handoff. Do not treat review artifacts as fabrication data.
---

# KiCad PCB Placement

Separate the heuristic review proposal from the electrical PCB. Circuit Weaver
does not generate a routable board during `generate`.

## 1. Generate and inspect the review bundle

```bash
circuit-weaver generate "${SPEC_PATH}" --output "${OUTPUT_DIR}"
```

Read these together:

- `assembly_manifest.json`: exhaustive physical-part inventory, including
  generated support passives;
- `placement_result.json`: proposed coordinates, exact reference
  reconciliation, quality findings, and `fabrication_ready: false`;
- `placement_review_context.json`: board constraints, placement rules, review
  blockers, targeted research prompts, and official/reference-layout links;
- `placement.svg`: editable vector proposal; and
- `placement_editor.html`: interactive drag/review tool that can export SVG.

Stop when `placement_result.json` is `blocked`, inventories do not match, or
the review gate reports unresolved overlaps, out-of-board parts, constraint
violations, missing support parents, missing footprint geometry/dimensions, or
unresolved sourcing. Never hide a blocker because the visual layout looks
reasonable. Use manufacturer datasheets and reference layouts as authority.

For an alternate optimizer configuration, run:

```bash
circuit-weaver optimize-placement "${SPEC_PATH}" \
  --strategy balanced --iterations 5000 --seed 42 \
  --output "${OUTPUT_DIR}/placement.json"
circuit-weaver placement-viewer "${SPEC_PATH}" \
  --output "${OUTPUT_DIR}/placement.html"
```

## 2. Apply physical-placement judgment

Review at minimum:

- connectors and controls against mechanical edges and enclosure constraints;
- decoupling/strap/bootstrap parts against their owning IC pins;
- regulator hot loops, switch-node copper, inductors, and current paths against
  the regulator reference layout;
- crystal loops, RF matching, antenna keepouts, USB/differential entry paths,
  and sensitive analog feedback;
- component rotations, pin-1 access, courtyard/rework spacing, thermal paths,
  fiducials, mounting hardware, and assembly-side constraints; and
- all explicit keepouts and placement constraints in the context artifact.

Edit `placement.svg` with the interactive editor or a standards-compliant
vector editor. Preserve each component's `data-ref`, transform, and layer
metadata. Do not add or duplicate assembly references.

## 3. Create the real electrical PCB

Open the manifest-selected root schematic in KiCad, assign and verify every
footprint, and run **Update PCB from Schematic**. Save a separate, pad-bearing,
named-net `.kicad_pcb`. This is the only valid target for placement, routing,
DFM, CPL, and Gerber work.

## 4. Reconcile and import the SVG

Dry-run first:

```bash
circuit-weaver import-placement "${OUTPUT_DIR}/placement.svg" \
  "${ELECTRICAL_PCB}" --output-pcb "${PLACED_PCB}" --dry-run
```

The default contract requires the SVG and PCB reference inventories to match
exactly. Duplicate, unexpected, missing, malformed, or non-finite placements
block publication. Apply only after the dry-run is clean:

```bash
circuit-weaver import-placement "${OUTPUT_DIR}/placement.svg" \
  "${ELECTRICAL_PCB}" --output-pcb "${PLACED_PCB}"
```

For a deliberate subset edit, opt in explicitly; unknown SVG references still
fail:

```bash
circuit-weaver import-placement subset.svg "${ELECTRICAL_PCB}" \
  --output-pcb "${PLACED_PCB}" --allow-partial
```

The command updates an existing sibling `<board-stem>_cpl.csv` when present;
it does not manufacture a trustworthy CPL from heuristic coordinates.

## 5. Verify in KiCad

- [ ] Reopen the written board without repair prompts.
- [ ] Confirm every assembly reference is present once with the intended
      footprint, side, rotation, and position.
- [ ] Run courtyard and full DRC checks.
- [ ] Check board-edge, connector, mounting, antenna, thermal, and height
      constraints against mechanical data.
- [ ] Keep support passives adjacent to their owning pins and minimize loop area.
- [ ] Route critical nets manually before any optional bulk autorouting.
- [ ] Generate CPL/Gerbers only from the reviewed real PCB.

For optional routing, use the repository `autoroute` skill and produce a
validated `.ses`; never invoke raw Freerouting flags by guesswork.
