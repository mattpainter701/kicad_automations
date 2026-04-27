from __future__ import annotations

import logging
from pathlib import Path

import pytest

from circuit_weaver import dispatcher as dispatcher_module
from circuit_weaver.dispatcher import ValidationReport, generate_artifacts
from circuit_weaver.sexpr_builder import validate_sexpr_balance


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
