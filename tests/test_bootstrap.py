from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import circuit_weaver


def test_package_import_exposes_version():
    assert circuit_weaver.__version__ == "0.4.0"


def test_cli_reports_version():
    result = subprocess.run(
        [sys.executable, "-m", "circuit_weaver", "--version"],
        capture_output=True,
        text=True,
        check=True,
    )

    assert result.stdout.strip() == "0.4.0"


def test_validate_command_accepts_example_spec():
    example = Path(__file__).resolve().parent.parent / "src" / "circuit_weaver" / "examples" / "iot_sensor.yaml"

    result = subprocess.run(
        [sys.executable, "-m", "circuit_weaver", "validate", str(example)],
        capture_output=True,
        text=True,
        check=True,
    )

    payload = json.loads(result.stdout)
    assert payload["valid"] is True
    assert payload["metadata"]["project"] == "IoT_Sensor"


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
        ],
        capture_output=True,
        text=True,
        check=True,
    )

    payload = json.loads(result.stdout)
    assert payload["valid"] is True
    assert (output_dir / "main.kicad_sch").exists()
    assert (output_dir / "canonical_spec.yaml").exists()
    assert (output_dir / "design_ir.json").exists()
