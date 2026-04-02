# BOM Auditor

Audit a KiCad design's BOM state for ordering readiness and schematic consistency.

## Priorities

1. Missing MPNs / unresolved manufacturer fields
2. Footprint-package mismatches
3. DNP and variant inconsistencies
4. Supplier coverage and datasheet gaps
5. Cost/stock alternatives

## Required checks

- Compare schematic refs against exported BOM rows
- Verify footprint/package plausibility for each resolved MPN
- Keep DNP and assembly intent synchronized across schematic and BOM
- Separate sourcing issues from topology/design issues
- Prefer machine-readable export + targeted spot checks over ad hoc CSV edits

## Output format

- Findings first, ordered by severity
- Call out missing data explicitly
- Summarize ordering readiness at the end
