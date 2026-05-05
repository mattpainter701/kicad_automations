# Circuit Weaver Architecture Principles

This repository is moving toward a part-neutral, vendor-agnostic, data/spec-driven engine. Treat the rules below as architectural constraints, not preferences.

## Core principles

- Keep engine behavior part-neutral. Runtime behavior should be driven by topology, normalized pin electrical types, declared interfaces, power domains, optional-pin metadata, and design spec intent, not by exact MPN matches.
- Keep ingestion vendor-agnostic. EasyEDA, LCSC, DigiKey, Mouser, datasheets, and local JSON are sources of evidence, not behavior selectors. Vendor IDs and supplier metadata may be stored as aliases or sourcing metadata, but they must not change circuit logic by themselves.
- Keep decisions data/spec-driven. If the engine needs a new fact, add it to normalized schema or imported metadata before adding new branching logic.
- Fail closed when metadata is incomplete. Do not silently substitute another part, synthesize arbitrary signal nets, or auto-no-connect unresolved required pins just to make generation succeed.

## What is allowed

- Dedicated builders are allowed when they represent a real topology or circuit family, such as buck regulators, USB-C CC handling, crystal networks, or other reusable behaviors that apply across many parts.
- Curated part entries are allowed as data. Good examples: pin maps, electrical types, interface membership, power-rail membership, recommended bypass/support passives, package aliases, vendor aliases, footprint hints.
- Named parts may be used as corpus fixtures for tests, validation, and acceptance gates.

## What is not allowed

- Do not add per-MPN Python branches when the behavior can be expressed through normalized metadata.
- Do not add supplier-specific logic that changes validation, repair, generation, or placement behavior.
- Do not rebuild the legacy template problem in JSON by encoding one-off behavioral exceptions per part.
- Do not upstream project-specific pin maps, BOM choices, footprints, or generated artifacts as generic engine behavior.

## Preferred implementation order

1. Express the requirement in the design spec or normalized import schema.
2. Normalize external source data into shared fields.
3. Make topology builders, validators, repair passes, and generators consume those shared fields.
4. Add corpus coverage proving the generic behavior works across multiple unrelated parts.

## Task-writing rule

- Write tasks in terms of capabilities, schema gaps, topology behavior, validation invariants, or import-pipeline coverage.
- If a task names a specific part, that part should be serving as a regression fixture or acceptance corpus member, not as the reason to add bespoke engine behavior.
