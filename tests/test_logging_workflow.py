"""Regression tests for Sprint 37 Task 159 — workflow logging hardening.

Locks in the contract the user reported missing in v0.25.x:

1. ``circuit-weaver.log`` is created for every CLI subcommand that operates
   on a spec file or output directory, not just ``generate``.
2. The log contains ``[command:step]`` workflow markers so users can see
   what the tool was doing.
3. INFO-level resolver/generator/validator messages propagate into the log.
4. ``CIRCUIT_WEAVER_LOG_LEVEL=DEBUG`` turns on byte-level trace when needed.
"""

from __future__ import annotations

import argparse
import logging
import subprocess
import sys
from pathlib import Path

import pytest

from circuit_weaver.logging_bridge import (
    _resolve_log_dir,
    cleanup_logging,
    init_logging_for_cli,
    log_workflow_step,
)


@pytest.fixture(autouse=True)
def _cleanup_logging():
    """Ensure each test starts and ends with no active logger."""
    cleanup_logging()
    yield
    cleanup_logging()


def _make_args(**kwargs) -> argparse.Namespace:
    return argparse.Namespace(**kwargs)


class TestResolveLogDir:
    def test_file_output_logs_to_parent(self, tmp_path):
        out_file = tmp_path / "report.html"
        d = _resolve_log_dir("review-report", _make_args(output=str(out_file)))
        assert d == tmp_path

    def test_dir_output_logs_to_dir(self, tmp_path):
        out_dir = tmp_path / "artifacts"
        d = _resolve_log_dir("generate", _make_args(output=str(out_dir)))
        assert d == out_dir

    def test_no_output_falls_back_to_spec_dir(self, tmp_path):
        spec_file = tmp_path / "design.yaml"
        spec_file.write_text("project: test\n", encoding="utf-8")
        d = _resolve_log_dir("validate", _make_args(spec=str(spec_file), output=None))
        assert d == tmp_path

    def test_no_log_command_returns_none(self, tmp_path):
        d = _resolve_log_dir("doctor", _make_args(output=None))
        assert d is None

    def test_unknown_command_falls_back_to_cwd(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        d = _resolve_log_dir("validate", _make_args(output=None))
        assert d == Path.cwd()


class TestInitLoggingForCli:
    def test_creates_log_file_in_target_dir(self, tmp_path):
        out = tmp_path / "out"
        init_logging_for_cli("generate", _make_args(output=str(out)))
        logging.getLogger("circuit_weaver.testing").info("hello world")
        log_path = out / "circuit-weaver.log"
        assert log_path.exists()
        assert "hello world" in log_path.read_text(encoding="utf-8")

    def test_workflow_step_appears_in_log(self, tmp_path):
        out = tmp_path / "out"
        init_logging_for_cli("generate", _make_args(output=str(out)))
        log_workflow_step("generate", "start", "CLI invoked: generate")
        contents = (out / "circuit-weaver.log").read_text(encoding="utf-8")
        assert "[generate:start]" in contents
        assert "CLI invoked" in contents

    def test_no_log_commands_skip_file(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        result = init_logging_for_cli("doctor", _make_args(output=None))
        assert result is None
        assert not (tmp_path / "circuit-weaver.log").exists()

    def test_debug_env_var_enables_debug(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CIRCUIT_WEAVER_LOG_LEVEL", "DEBUG")
        out = tmp_path / "out"
        init_logging_for_cli("generate", _make_args(output=str(out)))
        logging.getLogger("circuit_weaver.trace").debug("byte-level trace visible")
        log_text = (out / "circuit-weaver.log").read_text(encoding="utf-8")
        assert "byte-level trace visible" in log_text


class TestValidateCliWritesLog:
    """End-to-end: `circuit-weaver validate <yaml>` must produce a log file
    even though the command has no --output flag.
    """

    def test_validate_writes_log_to_spec_parent(self, tmp_path):
        # Copy the iot_sensor sample into tmp_path so we don't pollute the
        # real samples/ dir and can assert the log file appears.
        src = Path(__file__).resolve().parent.parent / "samples" / "iot_sensor_node" / "iot_sensor_node.yaml"
        dst_dir = tmp_path / "proj"
        dst_dir.mkdir()
        dst = dst_dir / "design.yaml"
        # We have to copy the full spec dir because the spec references
        # components_db or similar siblings. Do a plain text copy — the
        # validator doesn't need the full artefact bundle for this check.
        import shutil

        shutil.copy(src, dst)

        result = subprocess.run(
            [sys.executable, "-m", "circuit_weaver", "validate", str(dst)],
            capture_output=True,
            text=True,
            timeout=60,
        )
        # Exit code may be 0 or 1 depending on warnings; we only care that
        # the log file exists and is populated.
        assert result.returncode in (0, 1), f"validate returned {result.returncode}: stderr={result.stderr[:500]}"
        log_path = dst_dir / "circuit-weaver.log"
        assert log_path.exists(), f"Expected log at {log_path} but only found: {list(dst_dir.iterdir())}"
        contents = log_path.read_text(encoding="utf-8")
        assert "[validate:start]" in contents, "Workflow-start marker missing"
        assert "[validate:load-spec]" in contents, "load-spec marker missing"
        assert "INFO" in contents, "Should have at least one INFO-level entry"
