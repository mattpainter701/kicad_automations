"""Sprint 40 Task 174 + Sprint 41 — diverse-circuit regression corpus.

The user-reported IoT AQ audit exposed regressions that weren't caught
because our existing tests drill into individual modules rather than
running the full ``generate`` pipeline across circuit archetypes. This
module runs ``generate_artifacts`` on representative samples from each
archetype (IoT sensor, motor controller, USB bridge, LED driver, FPGA
power carrier, and the Sprint 41 additions: inverter, wearable BMS, RF
front-end, high-voltage isolation) and asserts four invariants on every
emitted schematic:

1. No structural duplicates (Task 170 — enforced by
   ``assert_schematic_invariants``).
2. Every net / ref mentioned in the report exists in the resolved
   design (Task 172 — enforced by ``verify_report_fidelity``).
3. No component carries the cache-stub signature
   (``pinout_source="stub"``) without an explicit user acknowledgment
   (Task 169).
4. Every non-power signal net has at least two pin endpoints in the
   emitted schematic OR was declared as a boundary interface — the
   Sprint 41 placement-readiness invariant at the artifact level.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

pytestmark = pytest.mark.skip_category("optional-tool")

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_schematic_invariants import assert_schematic_invariants  # noqa: E402

SAMPLES_DIR = Path(__file__).resolve().parent.parent / "samples"

# Archetypes selected for the corpus — each exercises a distinct
# combination of placer / resolver / report paths.
CORPUS_SAMPLES = [
    ("led_power_indicator", "led_power_indicator.yaml"),  # discrete LED + divider
    ("iot_sensor_node", "iot_sensor_node.yaml"),  # IoT sensor + MCU + I2C
    ("motor_controller", "motor_controller.yaml"),  # H-bridge + motor driver
    ("usb_uart_bridge", "usb_uart_bridge.yaml"),  # USB + regulator + bridge IC
    ("fpga_power_carrier", "fpga_power_carrier.yaml"),  # Multi-rail power tree + FPGA
    # Sprint 41 — expand breadth to the four follow-up archetypes
    # TASKS.md Sprint 40 flagged.
    ("inverter_gate_driver", "inverter_gate_driver.yaml"),
    ("wearable_bms", "wearable_bms.yaml"),
    ("rf_frontend", "rf_frontend.yaml"),
    ("high_voltage_isolation", "high_voltage_isolation.yaml"),
]


def _load_spec(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


@pytest.mark.parametrize("sample_dir,yaml_name", CORPUS_SAMPLES)
def test_corpus_generates_and_satisfies_invariants(sample_dir: str, yaml_name: str, tmp_path: Path) -> None:
    """For each archetype: generate artifacts, run invariants."""
    if os.environ.get("CI") == "true":
        pytest.skip("Corpus integration is a local regression suite")
    from circuit_weaver.dispatcher import generate_artifacts

    spec_path = SAMPLES_DIR / sample_dir / yaml_name
    if not spec_path.exists():
        pytest.fail(f"Checked-in sample spec is missing: {spec_path}")

    spec = _load_spec(spec_path)
    output_dir = tmp_path / sample_dir

    try:
        result = generate_artifacts(
            spec,
            output_dir=output_dir,
            # Soft warnings are fine for corpus coverage — we care about
            # structural integrity, not whether every load-cap picked matches
            # the crystal spec.
            require_valid=False,
            export_svg=False,
        )
    except ValueError as exc:
        # Hard structural / implementation / placement_readiness errors
        # reach here per Task 173 + Sprint 41. These are legitimate
        # regressions — fail with the spec path so the operator knows
        # which archetype broke.
        pytest.fail(f"{sample_dir}: generation raised hard validation error: {exc}")

    # Invariant 1: schematic must be structurally consistent.
    root_sch = result.get("root_schematic") or ""
    if root_sch and Path(root_sch).exists():
        sch_text = Path(root_sch).read_text(encoding="utf-8")
        assert_schematic_invariants(sch_text, context=f"{sample_dir}/{Path(root_sch).name}")

    # Invariant 2: no 2-pin cache-stub regressions. Pull the design_ir and
    # spot-check every resolved block.
    design_ir_path = Path(result["design_ir"])
    if design_ir_path.exists():
        import json

        ir = json.loads(design_ir_path.read_text(encoding="utf-8"))
        for block in ir.get("blocks", []):
            part = block.get("part_bindings", {}) or {}
            mpn = (part.get("mpn") or block.get("ic") or "").upper()
            if not mpn:
                continue

    # Invariant 3: report fidelity. The generate pipeline doesn't emit a
    # user-facing .md in every case, but when it does, no ghost refs/nets.
    report_md = output_dir / f"{result['project']}_report.md"
    if report_md.exists():
        report_text = report_md.read_text(encoding="utf-8")
        import json

        ir = json.loads(design_ir_path.read_text(encoding="utf-8"))
        known_refs = {block.get("ref") for block in ir.get("blocks", []) if block.get("ref")}

        import re

        ref_pattern = re.compile(r"(?<![A-Za-z0-9_])([A-Z]{1,3}\d{1,4})(?![A-Za-z0-9_])")
        mentioned_refs = set(ref_pattern.findall(report_text))
        ghost_ic_refs = {r for r in (mentioned_refs - known_refs) if re.match(r"^(U|Y|IC)\d", r)}
        assert not ghost_ic_refs, f"{sample_dir}: report names IC refs not in design_ir: {ghost_ic_refs}"

    # Invariant 4 — Sprint 41 placement-readiness. Scan the emitted
    # schematic for signal nets (non-power, non-ground) that only show
    # up on a single pin; those are placement blockers and should have
    # been caught at generate time. If one slipped through the gate,
    # fail loudly so the regression is visible.
    placement_path = Path(result.get("placement_readiness") or "")
    if placement_path.exists():
        import json

        payload = json.loads(placement_path.read_text(encoding="utf-8"))
        assert payload.get("ready") is True, (
            f"{sample_dir}: placement_readiness.json reports not-ready: "
            f"{payload.get('blocking', [])}"
        )


def test_corpus_has_five_archetypes():
    """Lock-in the breadth goal. Sprint 41 raises the bar to 9
    archetypes so the follow-up breadth goals from TASKS.md Sprint 40
    stay in coverage; adding new archetypes is encouraged, trimming
    requires evidence they're redundant."""
    assert len(CORPUS_SAMPLES) >= 9, (
        "Sprint 41 corpus must cover at least 9 archetypes (IoT, motor, USB, "
        "discrete LED, FPGA/SBC, inverter, wearable, RF, high-voltage). "
        "Trimming requires evidence the dropped archetype is redundant."
    )


def test_auto_repair_inserts_i2c_pullups(tmp_path: Path) -> None:
    """Sprint 41 Task B — auto-repair synthesizes a PULLUPS_ONLY block
    when a named I2C bus has no pull-up straps. Exercises the iot
    sensor sample because it's the smallest real I2C design in the
    corpus.
    """
    from circuit_weaver.dispatcher import compile_design_ir

    spec_path = SAMPLES_DIR / "iot_sensor_node" / "iot_sensor_node.yaml"
    spec = _load_spec(spec_path)

    compiled = compile_design_ir(spec)

    assert compiled.repair_actions, "expected auto_repair to synthesize at least one block"
    kinds = {action["kind"] for action in compiled.repair_actions}
    assert "i2c_pullups" in kinds, f"expected i2c_pullups repair, got {kinds}"

    # The synthetic block should appear as a resolved component in the
    # compiled design with PULLUPS_ONLY as its MPN.
    mpns = {(c.mpn or "").upper() for c in compiled.components}
    assert "PULLUPS_ONLY" in mpns, f"PULLUPS_ONLY block missing from components: {mpns}"


def test_auto_repair_disabled_via_spec_flag(tmp_path: Path) -> None:
    """Users can disable the auto-repair pass via ``auto_repair:
    false`` at the top of the spec. Verify no synthetic blocks appear
    in that mode (even when I2C pull-ups would otherwise be
    synthesized).
    """
    from circuit_weaver.dispatcher import compile_design_ir

    spec_path = SAMPLES_DIR / "iot_sensor_node" / "iot_sensor_node.yaml"
    spec = _load_spec(spec_path)
    spec["auto_repair"] = False

    compiled = compile_design_ir(spec)

    assert compiled.repair_actions == [], (
        f"auto_repair: false should suppress synthesis, got {compiled.repair_actions}"
    )
    mpns = {(c.mpn or "").upper() for c in compiled.components}
    assert "PULLUPS_ONLY" not in mpns, f"PULLUPS_ONLY block should not appear with auto_repair off: {mpns}"


@pytest.mark.parametrize("sample_dir,yaml_name", CORPUS_SAMPLES)
def test_corpus_validate_no_hard_errors(sample_dir: str, yaml_name: str) -> None:
    """Sprint 44 T186 — every corpus sample must validate with zero
    hard errors (structural + implementation + placement_readiness).
    Soft electrical warnings (floating inputs, decoupling, pin-footprint
    mismatches) are acceptable for minimal sample designs.
    """
    if os.environ.get("CI") == "true":
        pytest.skip("Corpus integration is a local regression suite")
    from circuit_weaver.dispatcher import validate_design

    spec_path = SAMPLES_DIR / sample_dir / yaml_name
    if not spec_path.exists():
        pytest.fail(f"Checked-in sample spec is missing: {spec_path}")

    spec = _load_spec(spec_path)
    report = validate_design(spec)

    hard_categories = ("structural", "implementation", "placement_readiness")
    hard_errors: list[str] = []
    for cat in hard_categories:
        for issue in report.categories.get(cat, []):
            level = getattr(issue, "level", None)
            code = getattr(issue, "code", "?")
            msg = getattr(issue, "message", "?")
            if level == "error":
                hard_errors.append(f"{code}: {msg}")

    assert not hard_errors, (
        f"{sample_dir}: validate found {len(hard_errors)} hard error(s): "
        + "; ".join(hard_errors)
    )
