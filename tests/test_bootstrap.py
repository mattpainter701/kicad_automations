from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import circuit_weaver


def test_package_import_exposes_version():
    assert circuit_weaver.__version__ == "0.7.0"


def test_cli_reports_version():
    result = subprocess.run(
        [sys.executable, "-m", "circuit_weaver", "--version"],
        capture_output=True,
        text=True,
        check=True,
    )

    assert result.stdout.strip() == "0.7.0"


def test_validate_command_accepts_example_spec():
    example = Path(__file__).resolve().parent.parent / "src" / "circuit_weaver" / "examples" / "iot_sensor.yaml"

    result = subprocess.run(
        [sys.executable, "-m", "circuit_weaver", "validate", str(example)],
        capture_output=True,
        text=True,
    )

    payload = json.loads(result.stdout)
    assert payload["metadata"]["project"] == "IoT_Sensor"
    # No structural or electrical errors (warnings are OK; KiCad CLI may not be installed)
    structural_errors = [m for m in payload["categories"].get("structural", []) if m["level"] == "error"]
    electrical_errors = [m for m in payload["categories"].get("electrical", []) if m["level"] == "error"]
    assert not structural_errors, f"Structural errors: {structural_errors}"
    assert not electrical_errors, f"Electrical errors: {electrical_errors}"


def test_generate_command_writes_example_artifacts(tmp_path: Path):
    example = Path(__file__).resolve().parent.parent / "src" / "circuit_weaver" / "examples" / "iot_sensor.yaml"
    output_dir = tmp_path / "out"

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "circuit_weaver",
            "generate",
            str(example),
            "--output",
            str(output_dir),
            "--no-svg",
            "--no-require-valid",
        ],
        capture_output=True,
        text=True,
    )

    # Generate should produce artifacts even when KiCad CLI is unavailable
    assert (output_dir / "main.kicad_sch").exists(), f"No schematic generated. stderr: {result.stderr[:500]}"
    assert (output_dir / "canonical_spec.yaml").exists()
    assert (output_dir / "design_ir.json").exists()
