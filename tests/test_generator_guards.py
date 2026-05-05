from __future__ import annotations

import logging
from pathlib import Path

import pytest

from circuit_weaver import dispatcher as dispatcher_module
from circuit_weaver.component_db import ComponentDef, PinDef
from circuit_weaver.design_ir import DesignIR
from circuit_weaver.dispatcher import ValidationReport, generate_artifacts
from circuit_weaver.generator import generate_from_components
from circuit_weaver.sexpr_builder import validate_sexpr_balance
from circuit_weaver.validator import ValidationCheckResult, ValidationIssue


def test_validate_sexpr_balance_warns_on_early_extra_close(caplog):
    with caplog.at_level(logging.WARNING, logger="circuit_weaver.sexpr_builder"):
        valid = validate_sexpr_balance(")(", "broken.kicad_sch")

    assert not valid
    assert "broken.kicad_sch" in caplog.text
    assert "min_depth=-1" in caplog.text


def test_generate_artifacts_writes_log_on_validation_failure(tmp_path: Path, monkeypatch):
    report = ValidationReport(
        profile="standard",
        valid=False,
        summary={"structural": 1, "electrical": 0, "implementation": 0, "presentation": 0},
        metadata={"project": "Broken"},
    )
    monkeypatch.setattr(dispatcher_module, "validate_design", lambda *args, **kwargs: report)
    monkeypatch.setattr(
        dispatcher_module,
        "compile_design_ir",
        lambda *args, **kwargs: pytest.fail("compile_design_ir should not run after validation failure"),
    )

    output_dir = tmp_path / "out"
    with pytest.raises(ValueError, match="Design failed standard validation"):
        generate_artifacts({"project": "Broken"}, output_dir=output_dir)

    log_path = output_dir / "circuit-weaver.log"
    assert log_path.exists(), "circuit-weaver.log not created on validation failure"
    content = log_path.read_text(encoding="utf-8")
    assert "Design failed standard validation" in content


def _test_comp(
    *,
    ref: str = "U1",
    pin_nets: dict[str, str] | None = None,
    power_pins: dict[str, str] | None = None,
    pins: list[PinDef] | None = None,
    unmapped_required_pins: dict[str, str] | None = None,
) -> ComponentDef:
    return ComponentDef(
        mpn=f"TEST_{ref}",
        ref_prefix="U",
        source_ref=ref,
        value=f"TEST_{ref}",
        footprint="Package_DFN_QFN:QFN-16-1EP_3x3mm_P0.5mm_EP1.7x1.7mm",
        category="digital",
        pins=pins
        or [
            PinDef("1", "SIG", "bidirectional", "L"),
            PinDef("2", "VDD", "power_in", "T"),
            PinDef("3", "GND", "power_in", "B"),
        ],
        pin_nets=pin_nets or {},
        power_pins=power_pins or {"2": "VDD_3P3", "3": "GND"},
        unmapped_required_pins=unmapped_required_pins or {},
    )


def test_generate_from_components_blocks_placement_readiness_for_direct_call(tmp_path: Path, monkeypatch):
    import circuit_weaver.generator as generator_module

    comp = _test_comp(pin_nets={"1": "FLOATING"})
    fake_results = [
        ValidationCheckResult(
            code="net-connectivity",
            label="Net connectivity",
            status="fail",
            issues=(
                ValidationIssue(
                    code="single-pin-net",
                    level="warning",
                    ref="U1",
                    mpn="TEST_U1",
                    message="Net 'FLOATING' has only one connection",
                ),
            ),
        )
    ]

    monkeypatch.setattr(generator_module, "run_validation_checks", lambda _components: fake_results)
    monkeypatch.setattr(
        generator_module,
        "allocate_sheets",
        lambda _components: pytest.fail("allocate_sheets should not run when readiness gate blocks"),
    )

    with pytest.raises(ValueError, match="placement_readiness error"):
        generate_from_components([comp], output_dir=tmp_path, validate=False, compiled_ir=DesignIR())


def test_generate_from_components_readiness_gate_override_allows_debug_emit(tmp_path: Path, monkeypatch):
    import circuit_weaver.generator as generator_module

    comp = _test_comp(pin_nets={"1": "FLOATING"})
    fake_results = [
        ValidationCheckResult(
            code="net-connectivity",
            label="Net connectivity",
            status="fail",
            issues=(
                ValidationIssue(
                    code="single-pin-net",
                    level="warning",
                    ref="U1",
                    mpn="TEST_U1",
                    message="Net 'FLOATING' has only one connection",
                ),
            ),
        )
    ]

    monkeypatch.setattr(generator_module, "run_validation_checks", lambda _components: fake_results)
    monkeypatch.setattr(
        generator_module,
        "allocate_sheets",
        lambda _components: (_ for _ in ()).throw(RuntimeError("reached allocation")),
    )

    with pytest.raises(RuntimeError, match="reached allocation"):
        generate_from_components([comp], output_dir=tmp_path, validate=False, readiness_gate=False)


def test_generate_from_components_hard_fails_unmapped_required_pin(tmp_path: Path):
    comp = _test_comp(
        pins=[
            PinDef("1", "PROG", "input", "L"),
            PinDef("2", "VDD", "power_in", "T"),
            PinDef("3", "GND", "power_in", "B"),
        ],
        unmapped_required_pins={"1": "PROG"},
    )

    with pytest.raises(ValueError, match="UNMAPPED signal pin 'PROG'"):
        generate_from_components([comp], output_dir=tmp_path, validate=False, readiness_gate=False)


def test_generate_from_components_hard_fails_floating_power_pin(tmp_path: Path):
    comp = _test_comp(
        pins=[PinDef("1", "VDD", "power_in", "L")],
        power_pins={},
    )

    with pytest.raises(ValueError, match="FLOATING power_in pin 'VDD'"):
        generate_from_components([comp], output_dir=tmp_path, validate=False, readiness_gate=False)
