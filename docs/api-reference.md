# API Reference

Public Python API for Circuit Weaver. All functions are in `circuit_weaver.mvp`.

```python
from circuit_weaver.mvp import (
    validate_design,
    apply_design_patch,
    generate_artifacts,
    diff_designs,
    ingest_pcb_feedback,
    generate_design_checklist,
)
```

---

## validate_design

```python
def validate_design(
    spec: dict[str, Any],
    *,
    profile: str = "mvp_strict",
    enrich_parts: bool = False,
    strict: bool = False,
) -> ValidationReport
```

Validate a design spec against the strict MVP profile.

**Parameters:**

| Name | Type | Default | Description |
|-|-|-|-|
| `spec` | dict | required | YAML-loaded design spec |
| `profile` | str | `"mvp_strict"` | Validation profile name |
| `enrich_parts` | bool | `False` | Query LCSC/DigiKey for missing part data before validation |
| `strict` | bool | `False` | Promote warnings to errors |

**Returns:** `ValidationReport` containing grouped check results (structural, electrical, implementation, presentation), pass/fail status, and a human-readable summary.

**Example:**

```python
import yaml
from circuit_weaver.mvp import validate_design

with open("design.yaml") as f:
    spec = yaml.safe_load(f)

report = validate_design(spec, strict=True)
print(report.summary)
for check in report.checks:
    print(f"  {check.code}: {check.status}")
```

---

## apply_design_patch

```python
def apply_design_patch(
    spec: dict[str, Any],
    patch: dict[str, Any],
    *,
    profile: str = "mvp_strict",
    enrich_parts: bool = False,
) -> dict[str, Any]
```

Apply a transactional patch to a design spec. Validates the result before accepting.

**Parameters:**

| Name | Type | Default | Description |
|-|-|-|-|
| `spec` | dict | required | Original design spec |
| `patch` | dict | required | Patch to apply (add/remove/modify blocks) |
| `profile` | str | `"mvp_strict"` | Validation profile |
| `enrich_parts` | bool | `False` | Enrich parts before validation |

**Returns:** dict with keys:
- `accepted` (bool) — whether the patch was accepted
- `updated_spec` (dict) — the patched spec (if accepted)
- `report` (ValidationReport) — validation results
- `diff` (dict) — semantic diff showing what changed

**Example:**

```python
patch = {
    "add": [
        {"section": "power", "template": "ldo", "ref": "U3", "ic": "ADP1706"}
    ]
}
result = apply_design_patch(spec, patch)
if result["accepted"]:
    spec = result["updated_spec"]
```

---

## generate_artifacts

```python
def generate_artifacts(
    spec: dict[str, Any],
    *,
    output_dir: str | Path,
    profile: str = "mvp_strict",
    require_valid: bool = True,
    enrich_parts: bool = False,
    export_svg: bool = True,
    score: bool = False,
    auto_source: bool = False,
    update_spec: bool = False,
    spec_path: Path | None = None,
    svg_placement: bool = False,
) -> dict[str, Any]
```

Generate KiCad schematic files and reports from a validated design spec.

**Parameters:**

| Name | Type | Default | Description |
|-|-|-|-|
| `spec` | dict | required | Design spec |
| `output_dir` | str or Path | required | Directory for generated files |
| `profile` | str | `"mvp_strict"` | Validation profile |
| `require_valid` | bool | `True` | Abort if validation fails |
| `enrich_parts` | bool | `False` | Enrich parts before generation |
| `export_svg` | bool | `True` | Export SVG previews of schematics |
| `score` | bool | `False` | Include electrical quality score |
| `auto_source` | bool | `False` | Auto-discover blank MPNs via DigiKey/Mouser APIs |
| `update_spec` | bool | `False` | Write discovered MPNs back to YAML spec |
| `spec_path` | Path | `None` | Original spec file path (required if `update_spec=True`) |
| `svg_placement` | bool | `False` | Export interactive SVG placement diagram |

**Returns:** dict with keys:
- `output_dir` (str) — path to output directory
- `project` (str) — project name
- `root_schematic` (str) — path to root `.kicad_sch` file
- `files` (list[str]) — all generated file paths
- `validation_report` (ValidationReport) — pre-generation validation
- `design_ir` (DesignIR) — compiled design IR
- `canonical_spec` (dict) — normalized spec
- `valid` (bool) — whether validation passed
- `auto_source_summary` (dict) — auto-source results (if `auto_source=True`)
- `placement_svg` (str) — path to placement.svg (if `svg_placement=True`)

---

## diff_designs

```python
def diff_designs(
    old_spec: dict[str, Any],
    new_spec: dict[str, Any],
) -> dict[str, Any]
```

Compute a semantic diff between two design specs at the IR level.

**Returns:** dict with keys:
- `metadata_changed` (dict) — changed metadata fields
- `added_blocks` (list) — blocks present in new but not old
- `removed_blocks` (list) — blocks present in old but not new
- `changed_blocks` (list) — blocks with field-level differences
- `added_interfaces` / `removed_interfaces` (list)
- `override_count_delta` (int) — change in override count
- `pcb_constraint_count_delta` (int) — change in constraint count
- `summary` (str) — human-readable summary

---

## ingest_pcb_feedback

```python
def ingest_pcb_feedback(
    spec: dict[str, Any],
    feedback: dict[str, Any],
) -> ConstraintFeedbackReport
```

Merge PCB-derived constraints and approved substitutions into the design spec.

**Parameters:**

| Name | Type | Description |
|-|-|-|
| `spec` | dict | Current design spec |
| `feedback` | dict | PCB feedback with `constraints` and `overrides` keys |

**Returns:** `ConstraintFeedbackReport` with:
- `accepted_constraints` (list) — constraints merged into spec
- `accepted_overrides` (list) — substitutions merged into spec
- `rejected` (list) — items that failed validation
- `updated_spec` (dict) — the updated spec

---

## generate_design_checklist

```python
def generate_design_checklist(
    report: ValidationReport,
    components=None,
) -> str
```

Generate a human-readable Markdown checklist for pre-fabrication review.

**Returns:** Markdown string with categorized checklist items based on validation results.

---

## Data Types

### ValidationReport

Returned by `validate_design()`. Contains:
- `checks` (list[ValidationCheckResult]) — individual check results
- `valid` (bool) — overall pass/fail
- `summary` (str) — human-readable summary
- `error_count` / `warning_count` (int)

### ValidationCheckResult

```python
@dataclass(frozen=True)
class ValidationCheckResult:
    code: str       # Check category (e.g., "decoupling")
    label: str      # Human-readable label
    status: str     # "PASS", "WARN", or "FAIL"
    issues: tuple[ValidationIssue, ...]
```

---

## SymbolResolver (symbol_resolver.py)

```python
from circuit_weaver.symbol_resolver import SymbolResolver

resolver = SymbolResolver()
comp_def, source = resolver.resolve("TPS61023DRLR")
print(f"Found via {source}: {comp_def.description}")  # Output: "Found via digikey: ..."
```

Unified 6-tier symbol resolution chain:
1. Custom registry
2. KiCad library
3. Symbol cache (30-day TTL)
4. EasyEDA (via LCSC)
5. DigiKey API
6. Mouser API

**Methods:**
- `resolve(mpn) -> (ComponentDef | None, source_str)` — resolve single MPN
- `resolve_batch(items) -> list[tuple[str, ComponentDef | None, str]]` — resolve multiple items

---

## SVG Placement Export/Import (svg_placement.py)

```python
from circuit_weaver.svg_placement import (
    export_placement_svg,
    import_placement_from_svg,
    update_kicad_pcb_placements,
    update_cpl_placements,
)

# Export to SVG
svg_str = export_placement_svg(
    components=[...],
    placements={"U1": {"x": 50, "y": 40, "rotation": 0, "layer": "front"}, ...},
    board_width_mm=100,
    board_height_mm=80,
    output_path="placement.svg"
)

# User edits placement.svg in Inkscape...

# Import edited placements back
placements = import_placement_from_svg("placement.svg")

# Update KiCad files
result = update_kicad_pcb_placements("design.kicad_pcb", placements, output_path="design.kicad_pcb")
cpl_count = update_cpl_placements("design_cpl.csv", placements, output_path="design_cpl.csv")
```

**Functions:**
- `export_placement_svg(components, placements, board_width_mm, board_height_mm, ...)` — generate SVG
- `import_placement_from_svg(svg_path)` — parse edited SVG back to placement dict
- `update_kicad_pcb_placements(kicad_pcb_path, placements, ...)` — update .kicad_pcb files
- `update_cpl_placements(cpl_path, placements, ...)` — update CPL CSV files

---

## SymbolCache (symbol_cache.py)

```python
from circuit_weaver.symbol_cache import SymbolCache

cache = SymbolCache()  # ~/.cache/circuit-weaver/symbols/

# Get cached entry
cached = cache.get("TPS61023DRLR")

# Store entry (30-day TTL)
cache.put("TPS61023DRLR", {
    "source": "digikey",
    "footprint": "Package_SO:SOIC-8_3.9x4.9mm_P1.27mm",
    "description": "Boost converter",
    "manufacturer": "Texas Instruments",
    "digikey_pn": "296-TPS61023DRLR-ND",
})

# Stats
stats = cache.stats()  # {total, fresh, stale, size_bytes}

# Clear cache
cache.clear(stale_only=True)  # Remove entries older than 30 days
```

---

### ValidationIssue

```python
@dataclass(frozen=True)
class ValidationIssue:
    code: str        # Check code or sub-code
    level: str       # "error" or "warning"
    ref: str         # Component reference (e.g., "U1")
    mpn: str         # Manufacturer part number
    message: str     # Description
    suggestion: str  # Actionable fix (may be empty)
```

### DesignIR, DesignBlock, DesignInterface

See [docs/design-ir-schema.md](design-ir-schema.md).

---

## Spec Harvesting (spec_harvester.py)

```python
from circuit_weaver.spec_harvester import harvest_specs

result = harvest_specs(spec, output_dir="./project", skip_download=False, delay=0.5)
# result["datasheets_dir"] → "project/datasheets"
# result["specs_dir"] → "project/specs"
# result["specs_extracted"] → number of components with extracted specs
```

Downloads datasheets and extracts structured parametric data for all BOM components. Outputs `datasheets/index.json`, `specs/ic_thermal.json`, `specs/passives.json`, `specs/si_params.json`.

---

## Datasheet Parser (datasheet_parser.py)

```python
from circuit_weaver.datasheet_parser import parse_datasheet, extract_specs

# Single PDF
specs = parse_datasheet("datasheets/TPS61023DRLR.pdf")
# specs → {"theta_ja": 45.2, "tj_max": 150, "fsw_mhz": 1.5, ...}

# Batch all PDFs
result = extract_specs("datasheets/", "specs/")
# result["output_file"] → "specs/metadata.json"
```

Requires `pypdf` (optional dependency). Extracts thermal (θJA, Pdiss, Tj_max), electrical (Vin, Vout, Iq, Fsw), and passive specs via regex patterns.

---

## SPICE Fetcher (spice_fetcher.py)

```python
from circuit_weaver.spice_fetcher import fetch_spice_models

result = fetch_spice_models(spec, output_dir="./project", include_s_params=False)
# result["spice_dir"] → "project/spice_models"
# result["spice_downloaded"] → count
```

Downloads SPICE models from TI, ADI, Microchip, ON Semi using known URL patterns. Graceful degradation when not found.

---

## Placement Optimizer (placement_optimizer.py)

```python
from circuit_weaver.placement_optimizer import optimize_placement, PlacementConfig

config = PlacementConfig(
    board_width_mm=100,
    board_height_mm=80,
    strategy="balanced",  # simple | thermal | si | cost | balanced
    iterations=5000,
    seed=42,
)

result = optimize_placement(components, config=config, specs_dir="specs/")
placements = result["placements"]
# placements → {"U1": {"x": 50.0, "y": 40.0, "rotation": 0, "layer": "front"}, ...}
```

Simulated annealing optimizer with cost functions for overlap, boundary, thermal proximity, and zone affinity. Reads thermal/SI specs from Sprint 15 output.

---

## Placement Viewer (placement_viewer.py)

```python
from circuit_weaver.placement_viewer import generate_viewer

html = generate_viewer(
    components,
    placements,
    board_width_mm=100,
    board_height_mm=80,
    thermal_data={"IC_U1": {"pdiss_max_w": 2.5}},
    output_path="viewer.html",
)
```

Generates an interactive HTML page with SVG board visualization, click-to-highlight nets, hover tooltips, thermal heatmap overlay, and CSV export.
