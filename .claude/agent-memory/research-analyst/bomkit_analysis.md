---
name: bomkit repo analysis
description: lamb356/bomkit — KiCad BOM/CPL export plugin + web dashboard + parts server, JLCPCB-focused
type: reference
---

## bomkit (github.com/lamb356/bomkit)

**Updated:** 2026-04-06. MIT license. Mono-repo with 3 packages.
**Status:** Single squashed commit (c6ed45a). Repo was force-pushed/rebased. All three packages now have code.

### Three packages

**bomkit-fab** (Python, KiCad plugin)
- pcbnew ActionPlugin: reads loaded PCB, resolves LCSC PNs from field aliases, applies JLCPCB rotation offsets, exports BOM + CPL CSVs
- JLCPCB part classifier (basic/preferred-extended/extended) from CSV parts DB
- Cost estimator: $3/unique extended part loading fee
- S-expr parser fallback for CLI/test use without pcbnew API
- wxPython dialog with sortable/filterable parts table
- Rotation DB: regex-based, 39 rules, project-level overrides via `rotations_custom.csv`
- Field aliasing: LCSC (8 aliases), MPN (13), Manufacturer (9)
- pytest suite: 8 test files

**bomkit-dashboard** (Next.js 16 / React 19 / TypeScript)
- Web app for persistent BOM workspace across revisions
- Stack: Next.js + Drizzle ORM + Neon Postgres + NextAuth + Stripe + TanStack Table
- **Revision diffing**: detects added/removed/changed rows between BOM revisions (by designator key)
- **Carry-forward**: preserves locked sourcing choices across revisions
- **JLC fee intelligence**: classifies parts via jlcsearch.tscircuit.com API, calculates loading fees at 5/10/30/50/100 qty
- **Local offers**: manual price/MOQ/lead-time entries per row
- **Locked choices**: pin a sourcing decision (source, SKU, unit price) to a BOM row
- CSV parsers: auto-detects BOMKit Fab export and KiCad Symbol Fields CSV formats
- Tiered pricing: Free (1 project, 50 rows), Solo ($15/mo), Pro ($29/mo)
- Deploy target: Vercel (currently blocked by token issue per BLOCKED.md)

**bomkit-parts** (Python, HTTP server)
- Minimal HTTP parts catalog server (stdlib http.server)
- Serves curated parts from `seed_parts.json`
- Endpoints: /categories, /parts?category_id=X, /parts/{id}
- Lightweight, no external dependencies

### What bomkit does NOT do
- No distributor API search (DigiKey, Mouser, LCSC direct) -- relies on jlcsearch community API only
- No datasheet fetching or sync
- No schematic analysis (PCB-only for fab, CSV import for dashboard)
- No schematic property writing (doesn't write back to .kicad_sch)
- No stock checking beyond jlcsearch
- No per-distributor order file generation
- No BOM-to-schematic round-trip

### Unique capabilities vs our tooling
1. **Rotation offset DB** -- 39 regex rules for JLCPCB CPL correction. We don't have this.
2. **Revision-aware BOM diffing** in web UI -- we have CLI-level BOM diffing concept but no persistent workspace.
3. **Carry-forward locked choices** -- persists sourcing decisions across design revisions.
4. **JLCPCB fee calculator** at multiple qty breakpoints -- we estimate but less structured.
5. **KiCad pcbnew plugin UI** -- wxPython dialog inside KiCad itself. We're CLI-only.
