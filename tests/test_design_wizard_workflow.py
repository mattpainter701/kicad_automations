"""Regression tests for the standalone design-wizard lifecycle."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from circuit_weaver.dispatcher import _handle_design_workflow, _run_design_wizard
from circuit_weaver.project_spec import _parse_yaml


def _stdin_must_not_be_read(_prompt: str = "") -> str:
    raise AssertionError("--dry-run attempted to read stdin")


def test_run_wizard_dry_run_never_reads_stdin_and_keeps_requested_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project_root = tmp_path / "requested-root"
    monkeypatch.setattr("builtins.input", _stdin_must_not_be_read)

    spec, logger = _run_design_wizard(
        project_root,
        project_name_override="Name/That/Must/Not/Become/A/Path",
        research_backend="standard",
        research_depth="fast",
        dry_run=True,
    )

    assert spec is not None
    assert logger is not None
    assert logger.project_dir == project_root.resolve()
    assert logger.log_path == project_root.resolve() / "design.log"
    assert not (tmp_path / "Name" / "That").exists()


def test_handle_wizard_honors_exact_output_and_is_noninteractive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = tmp_path / "deliver-here" / "custom-name.yaml"
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("builtins.input", _stdin_must_not_be_read)

    _handle_design_workflow(
        dry_run=True,
        output=str(output),
        research_backend="standard",
        research_depth="fast",
    )

    assert output.is_file()
    assert (output.parent / "design.log").is_file()
    assert not (tmp_path / "MyCircuit_v1").exists()
    payload = _parse_yaml(output)
    assert payload["project"] == "custom-name"
    assert payload["metadata"]["research_depth"] == "fast"


def test_resume_continues_intake_and_preserves_existing_design(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "existing" / "design.yaml"
    source.parent.mkdir()
    source.write_text(
        """\
project: ResumeBoard
metadata:
  title: ResumeBoard
  wizard_context:
    experience: Professional
    purpose: Existing precision instrument
    form_factor: 40x30mm
blocks:
  sensor:
    ref: U7
    kind: component
    ic: SHT41
pcb_constraints:
  - kind: keepout
    name: antenna
custom_release_field: preserve-me
""",
        encoding="utf-8",
    )
    resumed_output = tmp_path / "continued" / "continued.yaml"
    monkeypatch.setattr("builtins.input", _stdin_must_not_be_read)

    _handle_design_workflow(
        resume=str(source),
        output=str(resumed_output),
        dry_run=True,
        research_backend="standard",
        research_depth="normal",
    )

    resumed = _parse_yaml(resumed_output)
    original = _parse_yaml(source)
    assert resumed["blocks"] == original["blocks"]
    assert resumed["pcb_constraints"] == original["pcb_constraints"]
    assert resumed["custom_release_field"] == "preserve-me"
    assert resumed["metadata"]["wizard_context"]["purpose"] == "Existing precision instrument"
    assert resumed["metadata"]["wizard_context"]["form_factor"] == "40x30mm"
    assert source.read_text(encoding="utf-8").startswith("project: ResumeBoard")


def test_resume_interactively_updates_requirements_without_replacing_blocks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "design.yaml"
    source.write_text(
        """\
project: InteractiveResume
blocks:
  retained:
    ref: U9
    kind: component
    ic: KEEP-ME
custom: retained
""",
        encoding="utf-8",
    )
    answers = iter(
        [
            "Advanced",
            "Updated motor controller requirements",
            "55x35mm",
            "24V",
            "5V, 2A",
            "CAN, UART",
            "STM32G4",
            "DRV8353",
            "low EMI",
        ]
    )
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(answers))

    _handle_design_workflow(
        resume=str(source),
        dry_run=False,
        research_backend="standard",
        research_depth="normal",
    )

    resumed = _parse_yaml(source)
    context = resumed["metadata"]["wizard_context"]
    assert context["experience"] == "Advanced"
    assert context["purpose"] == "Updated motor controller requirements"
    assert context["input_power"] == "24V"
    assert resumed["blocks"]["retained"]["ic"] == "KEEP-ME"
    assert resumed["custom"] == "retained"


def test_resume_json_writes_valid_json_to_explicit_json_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "design.json"
    source.write_text(json.dumps({"project": "JsonBoard", "blocks": [], "custom": {"keep": True}}), encoding="utf-8")
    output = tmp_path / "copy.json"
    monkeypatch.setattr("builtins.input", _stdin_must_not_be_read)

    _handle_design_workflow(
        resume=str(source),
        output=str(output),
        dry_run=True,
        research_backend="standard",
        research_depth="normal",
    )

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["project"] == "JsonBoard"
    assert payload["blocks"] == []
    assert payload["custom"] == {"keep": True}


def test_design_wizard_cli_dispatches_output_and_dry_run(tmp_path: Path) -> None:
    output = tmp_path / "cli" / "board.yaml"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "circuit_weaver",
            "design-wizard",
            "--dry-run",
            "--research-backend",
            "standard",
            "--output",
            str(output),
        ],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert output.is_file()
    assert "Design saved" in result.stdout


def test_resume_missing_spec_fails_truthfully(tmp_path: Path) -> None:
    missing = tmp_path / "missing.yaml"

    with pytest.raises(SystemExit) as exc_info:
        _handle_design_workflow(resume=str(missing), dry_run=True)

    assert exc_info.value.code == 1
    assert not missing.exists()
