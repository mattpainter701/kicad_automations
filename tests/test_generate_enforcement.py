"""Sprint 40 Task 173 — ``generate`` enforcement is deterministic.

The IoT AQ audit showed one run correctly raising ``Design failed standard
validation`` on 8 ``missing-footprint`` errors, then a follow-up run
proceeding past the same errors because the user passed
``--no-require-valid`` (or ``require_valid=False``). That flag existed as a
blanket bypass — it let hard structural / implementation errors through
silently, producing artifacts that were internally broken.

Policy lock-in:

* Structural + implementation errors ALWAYS block generation, regardless
  of ``require_valid``.
* ``--no-require-valid`` only relaxes soft electrical warnings (dangling
  dev signals, crystal load-cap tolerance, etc.).
* Two runs on the same spec with the same cache state must reach the same
  verdict.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from circuit_weaver.dispatcher import ValidationMessage, ValidationReport, generate_artifacts


class _FakeReport(ValidationReport):
    pass


def _report_with_missing_footprint() -> ValidationReport:
    return ValidationReport(
        profile="standard",
        valid=False,
        categories={
            "structural": [],
            "electrical": [],
            "implementation": [
                ValidationMessage(
                    category="implementation",
                    code="missing-footprint",
                    level="error",
                    subject="U2",
                    message="Resolved block has no footprint binding",
                ),
            ],
            "presentation": [],
        },
        summary={"structural": 0, "electrical": 0, "implementation": 1, "presentation": 0},
        metadata={"project": "test"},
    )


def _report_soft_warnings_only() -> ValidationReport:
    return ValidationReport(
        profile="standard",
        valid=False,
        categories={
            "structural": [],
            "electrical": [
                ValidationMessage(
                    category="electrical",
                    code="net-connectivity",
                    level="warning",
                    subject="U1",
                    message="SWDIO has only one connection (pin 37 on U1) — likely dangling",
                ),
            ],
            "implementation": [],
            "presentation": [],
        },
        summary={"structural": 0, "electrical": 1, "implementation": 0, "presentation": 0},
        metadata={"project": "test"},
    )


def test_implementation_error_blocks_even_with_no_require_valid(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """The bypass flag must NOT let a missing-footprint error through.
    This is the regression gate for the IoT AQ audit pattern."""
    import circuit_weaver.dispatcher as dispatcher

    monkeypatch.setattr(dispatcher, "validate_design", lambda *a, **kw: _report_with_missing_footprint())

    spec = {"project": "test", "blocks": []}
    with pytest.raises(ValueError) as excinfo:
        generate_artifacts(
            spec,
            output_dir=tmp_path / "with_bypass",
            require_valid=False,
        )
    msg = str(excinfo.value)
    assert "structural/implementation error" in msg or "hard validation" in msg or "not bypassable" in msg


def test_implementation_error_blocks_by_default(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Default require_valid=True also blocks on the same error."""
    import circuit_weaver.dispatcher as dispatcher

    monkeypatch.setattr(dispatcher, "validate_design", lambda *a, **kw: _report_with_missing_footprint())

    spec = {"project": "test", "blocks": []}
    with pytest.raises(ValueError):
        generate_artifacts(spec, output_dir=tmp_path / "default")


def test_soft_warning_is_bypassable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog):
    """Dangling SWDIO / SWO warnings are soft — ``--no-require-valid``
    may proceed past them, but the bypass is logged."""
    import circuit_weaver.dispatcher as dispatcher

    monkeypatch.setattr(dispatcher, "validate_design", lambda *a, **kw: _report_soft_warnings_only())

    # Stub out the downstream compile / generate path so we only exercise
    # the enforcement gate.
    class _StubCompiled:
        ir = type("IR", (), {"to_dict": lambda self: {}, "blocks": []})()
        metadata = {"project": "test"}
        components: list = []

    monkeypatch.setattr(dispatcher, "compile_design_ir", lambda *a, **kw: _StubCompiled())
    monkeypatch.setattr(dispatcher, "_generate_compiled_artifacts", lambda *a, **kw: ([], None))
    # test_point_gen and firmware_export both get called downstream; null them out.
    from circuit_weaver import firmware_export, test_point_gen

    monkeypatch.setattr(test_point_gen, "generate_test_point_artifacts", lambda *a, **kw: {})
    monkeypatch.setattr(firmware_export, "is_mcu", lambda comp: False)

    spec = {"project": "test", "blocks": []}
    with caplog.at_level("WARNING", logger="circuit_weaver.dispatcher"):
        result = generate_artifacts(
            spec,
            output_dir=tmp_path / "soft_bypass",
            require_valid=False,
        )
    assert result["valid"] is False  # was never valid, but generation proceeded
    assert any("--no-require-valid" in rec.getMessage() for rec in caplog.records), (
        "bypass of soft warnings must be logged loudly"
    )


def test_deterministic_verdict_across_runs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Two invocations on the same spec with the same validator state must
    reach the same verdict. Non-determinism is how the IoT AQ audit ended
    up with one session raising and the next succeeding on identical
    inputs.
    """
    import circuit_weaver.dispatcher as dispatcher

    reports = [_report_with_missing_footprint(), _report_with_missing_footprint()]

    def _fake_validate(*_args, **_kwargs):
        return reports.pop(0)

    monkeypatch.setattr(dispatcher, "validate_design", _fake_validate)

    spec = {"project": "test", "blocks": []}
    with pytest.raises(ValueError):
        generate_artifacts(spec, output_dir=tmp_path / "run1")
    with pytest.raises(ValueError):
        generate_artifacts(spec, output_dir=tmp_path / "run2", require_valid=False)
