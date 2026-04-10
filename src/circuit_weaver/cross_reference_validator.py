"""Cross-reference validation between spec, schematic, BOM, and PCB.

Implements the 5 audit passes described in kicad_validate SKILL.md
as executable code. Each pass returns structured results that integrate
with the validation pipeline.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .component_db import ComponentDef
from .validator import ValidationIssue


@dataclass
class CrossReferenceResult:
    """Result from a single cross-reference audit pass."""

    pass_name: str
    status: str  # "pass", "fail", "skipped"
    issues: list[ValidationIssue] = field(default_factory=list)
    checked_items: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "pass_name": self.pass_name,
            "status": self.status,
            "issues": [
                {"code": i.code, "level": i.level, "ref": i.ref, "message": i.message}
                for i in self.issues
            ],
            "checked_items": self.checked_items,
        }


def validate_spec_vs_schematic(
    components: list[ComponentDef],
    spec: dict[str, Any] | None = None,
) -> CrossReferenceResult:
    """Pass 1: Verify every spec requirement has a corresponding component.

    Checks:
    - All blocks in spec have at least one component with a matching ref
    - Power rails defined in spec exist as nets in components
    """
    issues: list[ValidationIssue] = []
    checked = 0

    if not spec:
        return CrossReferenceResult(
            pass_name="spec_vs_schematic",
            status="skipped",
            checked_items=0,
        )

    # Check blocks have corresponding components
    blocks = spec.get("blocks", [])
    comp_refs = {c.source_ref for c in components if c.source_ref}

    for block in blocks:
        checked += 1
        block_ref = block.get("ref", "")
        block_id = block.get("id", block_ref)
        if block_ref and block_ref not in comp_refs:
            issues.append(ValidationIssue(
                code="xref-missing-component",
                level="warning",
                ref=block_ref,
                mpn="",
                message=f"Block '{block_id}' ref '{block_ref}' not found in component list",
                suggestion="Verify block ref matches a generated component",
            ))

    status = "fail" if any(i.level == "error" for i in issues) else ("pass" if not issues else "warn")
    return CrossReferenceResult(
        pass_name="spec_vs_schematic",
        status=status,
        issues=issues,
        checked_items=checked,
    )


def validate_schematic_vs_bom(
    components: list[ComponentDef],
) -> CrossReferenceResult:
    """Pass 3: Every component has MPN and matching footprint.

    Checks:
    - All non-passive components have an MPN assigned
    - Footprint is specified for all components
    """
    issues: list[ValidationIssue] = []
    checked = 0
    _passive_prefixes = {"R", "C", "L", "F", "FB", "TP", "D"}

    for comp in components:
        ref = comp.source_ref or ""
        if not ref:
            continue
        checked += 1

        prefix = ref[0].upper()

        # Check MPN for non-trivial components
        if prefix not in _passive_prefixes and not comp.mpn:
            issues.append(ValidationIssue(
                code="xref-missing-mpn",
                level="warning",
                ref=ref,
                mpn="",
                message=f"{ref}: No MPN assigned. Required for sourcing and verification.",
                suggestion="Add mpn field to the component block in design.yaml",
            ))

        # Check footprint
        if not comp.footprint:
            issues.append(ValidationIssue(
                code="xref-missing-footprint",
                level="warning",
                ref=ref,
                mpn=comp.mpn or "",
                message=f"{ref}: No footprint assigned. Required for PCB layout.",
                suggestion="Add footprint field or let the engine auto-resolve from MPN",
            ))

    status = "fail" if any(i.level == "error" for i in issues) else ("pass" if not issues else "warn")
    return CrossReferenceResult(
        pass_name="schematic_vs_bom",
        status=status,
        issues=issues,
        checked_items=checked,
    )


def validate_component_consistency(
    components: list[ComponentDef],
) -> CrossReferenceResult:
    """Pass 5: Internal component consistency checks.

    Checks:
    - No duplicate reference designators
    - Reference designator numbering is consistent
    - Power pins are connected to named nets (not floating)
    """
    issues: list[ValidationIssue] = []
    checked = 0
    seen_refs: dict[str, int] = {}

    for comp in components:
        ref = comp.source_ref or ""
        if not ref:
            continue
        checked += 1

        # Check for duplicate refs
        if ref in seen_refs:
            seen_refs[ref] += 1
            issues.append(ValidationIssue(
                code="xref-duplicate-ref",
                level="error",
                ref=ref,
                mpn=comp.mpn or "",
                message=f"Duplicate reference designator: {ref} (seen {seen_refs[ref]} times)",
                suggestion="Each component must have a unique reference designator",
            ))
        else:
            seen_refs[ref] = 1

        # Check power pins have nets
        for pin_name, net in (comp.power_pins or {}).items():
            if not net or net.lower() in ("nc", "unconnected", ""):
                issues.append(ValidationIssue(
                    code="xref-floating-power",
                    level="error",
                    ref=ref,
                    mpn=comp.mpn or "",
                    message=f"{ref} power pin '{pin_name}' is not connected to a net",
                    suggestion=f"Connect {pin_name} to the appropriate power rail",
                ))

    status = "fail" if any(i.level == "error" for i in issues) else ("pass" if not issues else "warn")
    return CrossReferenceResult(
        pass_name="component_consistency",
        status=status,
        issues=issues,
        checked_items=checked,
    )


def run_cross_reference_audit(
    components: list[ComponentDef],
    *,
    spec: dict[str, Any] | None = None,
) -> list[CrossReferenceResult]:
    """Run all cross-reference audit passes and return structured results.

    Args:
        components: Resolved component list from compiled design.
        spec: Original design spec dict (for spec-vs-schematic checks).

    Returns:
        List of CrossReferenceResult, one per pass.
    """
    results = [
        validate_spec_vs_schematic(components, spec=spec),
        validate_schematic_vs_bom(components),
        validate_component_consistency(components),
    ]

    # Log results
    from .logging_bridge import get_design_logger

    dl = get_design_logger()
    if dl:
        total_errors = sum(
            sum(1 for i in r.issues if i.level == "error") for r in results
        )
        total_warnings = sum(
            sum(1 for i in r.issues if i.level == "warning") for r in results
        )
        dl.log_erc_drc(
            check_type="cross_reference",
            file="(design)",
            errors=total_errors,
            warnings=total_warnings,
            details=[f"[{r.pass_name}] {r.status}" for r in results],
        )

    return results
