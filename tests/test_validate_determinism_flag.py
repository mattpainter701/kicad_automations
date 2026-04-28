"""Sprint 45 Bug 3 — validate_design(check_determinism=False) skips the
dual-pass artifact generation, halving the work when the caller is about
to generate the real artifact anyway.

Regression: prior to Sprint 45, generate_artifacts() called
validate_design() which always ran the artifact generation pipeline twice
(temp dirs schematic_mvp_validate_a_* and schematic_mvp_validate_b_*) to
catch non-deterministic UUID drift, then generate_artifacts() ran a third
generation for the real output. Net effect: 3 schematic generations per
single ``circuit-weaver generate`` invocation.

The IoT_AQ_Sensor v2 design.log shows three back-to-back validation
entries followed by the BME688 floating-pin warning emitted three times
in a row, confirming the triple generation.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from circuit_weaver.dispatcher import validate_design

SAMPLES_DIR = Path(__file__).resolve().parent.parent / "samples"


def _load_spec(name: str) -> dict:
    from circuit_weaver.project_spec import _parse_yaml

    yaml_path = SAMPLES_DIR / name / f"{name}.yaml"
    assert yaml_path.exists(), f"Sample not found at {yaml_path}"
    return _parse_yaml(yaml_path)


def test_validate_with_determinism_runs_artifact_pipeline_twice():
    """Default behavior: dual-pass for non-determinism detection."""
    spec = _load_spec("led_power_indicator")
    with patch("circuit_weaver.dispatcher._generate_compiled_artifacts") as mock_gen:
        mock_gen.return_value = ([], None)
        # We patched the inner generator, so the validator can't actually
        # produce a root schematic — it will append a missing-root-schematic
        # error. That's fine; we only care about call count here.
        validate_design(spec, check_determinism=True)

    # 2 calls: run A + run B
    assert mock_gen.call_count == 2, (
        f"With check_determinism=True, expected 2 generation passes, got {mock_gen.call_count}"
    )


def test_validate_without_determinism_runs_artifact_pipeline_once():
    """Sprint 45 Bug 3: check_determinism=False halves the work."""
    spec = _load_spec("led_power_indicator")
    with patch("circuit_weaver.dispatcher._generate_compiled_artifacts") as mock_gen:
        mock_gen.return_value = ([], None)
        validate_design(spec, check_determinism=False)

    assert mock_gen.call_count == 1, (
        f"With check_determinism=False, expected 1 generation pass, got {mock_gen.call_count}"
    )


def test_generate_artifacts_does_not_triple_generate(tmp_path):
    """End-to-end: generate_artifacts should result in exactly 2 generations
    (1 from validate's smoke pass, 1 from the real output write), not 3."""
    from circuit_weaver.dispatcher import generate_artifacts

    spec = _load_spec("led_power_indicator")

    # Wrap the inner pipeline call to count invocations across both
    # validate_design (1 call expected with our flag) and generate's write
    # (another 1 call).
    with patch(
        "circuit_weaver.dispatcher._generate_compiled_artifacts",
        wraps=__import__(
            "circuit_weaver.dispatcher",
            fromlist=["_generate_compiled_artifacts"],
        )._generate_compiled_artifacts,
    ) as wrapped:
        try:
            generate_artifacts(spec, output_dir=tmp_path)
        except Exception:
            # Even if generation fails downstream, count what ran
            pass

    # Pre-fix: 3 calls (validate run-A, validate run-B, real generate).
    # Post-fix: 2 calls (validate smoke, real generate).
    assert wrapped.call_count == 2, (
        f"generate_artifacts should invoke _generate_compiled_artifacts "
        f"exactly 2 times (1 smoke + 1 real); got {wrapped.call_count}"
    )


def test_check_determinism_default_is_true():
    """Backward compatibility: existing direct callers of validate_design
    continue to get the dual-pass determinism check."""
    import inspect

    sig = inspect.signature(validate_design)
    param = sig.parameters.get("check_determinism")
    assert param is not None, "validate_design must accept check_determinism"
    assert param.default is True, (
        f"check_determinism must default to True (back-compat), got {param.default}"
    )
