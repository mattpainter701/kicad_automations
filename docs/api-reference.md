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

**Returns:** dict with keys:
- `output_dir` (str) — path to output directory
- `project` (str) — project name
- `root_schematic` (str) — path to root `.kicad_sch` file
- `files` (list[str]) — all generated file paths
- `validation_report` (ValidationReport) — pre-generation validation
- `design_ir` (DesignIR) — compiled design IR
- `canonical_spec` (dict) — normalized spec
- `valid` (bool) — whether validation passed

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
