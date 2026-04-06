# CLI Reference

All commands use the `circuit-weaver` entry point (or `python -m circuit_weaver.mvp`).

## validate

Validate a canonical or legacy design spec.

```bash
circuit-weaver validate <spec.yaml> [--strict] [--enrich-parts]
```

| Flag | Description |
|-|-|
| `--strict` | Treat warnings as errors (production gate) |
| `--enrich-parts` | Query LCSC/DigiKey to fill missing part data before validation |

**Exit codes:** 0 = valid, 1 = validation errors found.

---

## generate

Generate KiCad artifacts from a validated design spec.

```bash
circuit-weaver generate <spec.yaml> --output <dir> [flags]
```

| Flag | Description |
|-|-|
| `--output`, `-o` | Output directory (required) |
| `--no-require-valid` | Generate even if validation fails |
| `--no-svg` | Skip SVG export |
| `--presentation-profile` | `default` or `review` (changes schematic layout) |
| `--enrich-parts` | Query distributors for missing part data |
| `--score` | Include electrical quality score in report |

**Outputs:** `.kicad_sch` files, `_report.md`, placement hints, SVGs.

---

## apply-patch

Apply a transactional patch to a design spec. Validates before accepting.

```bash
circuit-weaver apply-patch <spec.yaml> <patch.yaml> [--output <file>] [--enrich-parts]
```

| Flag | Description |
|-|-|
| `--output`, `-o` | Write updated spec to file (default: stdout) |
| `--enrich-parts` | Enrich parts before validation |

**Exit codes:** 0 = patch accepted, 1 = patch rejected (validation failed).

---

## diff

Compare two design specs structurally.

```bash
circuit-weaver diff <old.yaml> <new.yaml> [--svg] [--output <file>]
```

| Flag | Description |
|-|-|
| `--svg` | Generate visual HTML diff with side-by-side SVG schematics |
| `--output`, `-o` | Write HTML report to file (requires `--svg`) |

**Without flags:** JSON semantic diff to stdout.
**With `--svg`:** HTML report with color-coded block changes.

---

## ingest-pcb-feedback

Merge PCB layout constraints back into the design spec.

```bash
circuit-weaver ingest-pcb-feedback <spec.yaml> <feedback.yaml> [--output <file>]
```

Accepts constraint additions (placement, routing) and approved component substitutions.

---

## list-templates

List all available subcircuit templates.

```bash
circuit-weaver list-templates [--json] [--verbose]
```

| Flag | Description |
|-|-|
| `--json` | Machine-readable JSON output |
| `--verbose` | Include full parameter schema with types, defaults, and options |

---

## scaffold

Generate a YAML design spec stub from a template.

```bash
circuit-weaver scaffold [--template TYPE] [--ref REF] [--output <file>]
```

| Flag | Description |
|-|-|
| `--template` | Template type (e.g., `buck`, `ldo`, `i2c_bus`) |
| `--ref` | Reference designator (e.g., `U1`) |
| `--output`, `-o` | Write to file (default: stdout) |

**No arguments:** Lists available templates.

---

## cost-bom

Show costed BOM with LCSC pricing at volume breaks.

```bash
circuit-weaver cost-bom <spec.yaml> [--qty 1,10,100,1000] [--json]
```

| Flag | Description |
|-|-|
| `--qty` | Comma-separated build quantities (default: 1,10,100,1000) |
| `--json` | Machine-readable JSON output |

Queries the LCSC/jlcsearch API for real-time pricing. Flags out-of-stock and unresolvable parts.

---

## export-jlcpcb

Export JLCPCB-formatted BOM and CPL files for assembly ordering.

```bash
circuit-weaver export-jlcpcb <spec.yaml> --output <dir>
```

**Outputs:** `bom.csv` (Comment, Designator, Footprint, LCSC Part#), `cpl.csv` (placement), `README.txt` (upload instructions).

---

## export-gerbers

Export Gerber and drill files from a KiCad PCB.

```bash
circuit-weaver export-gerbers <board.kicad_pcb> --output <dir> [--layers <list>]
```

| Flag | Description |
|-|-|
| `--output`, `-o` | Output directory (required) |
| `--layers` | Custom layer selection (default: all copper + mask + silk + edge) |

Requires KiCad CLI (`kicad-cli`) to be installed and on PATH.

---

## design-wizard

Interactive offline design wizard. No agents or APIs required.

```bash
circuit-weaver design-wizard [--output <file>]
```

Walks through requirements capture, template selection, and spec generation step-by-step.

---

## autoroute

Route a KiCad PCB using Freerouting.

```bash
circuit-weaver autoroute <board.kicad_pcb> [--output <file>]
```

Requires Freerouting to be installed separately.

---

## log-status

Show workflow log status for a project directory.

```bash
circuit-weaver log-status <project_dir>
```
