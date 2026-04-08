"""End-to-end CLI tests for all circuit-weaver subcommands.

Tests actual CLI invocation via subprocess — catches flag parsing,
import errors, and crash-on-startup bugs that unit tests miss.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

_SAMPLE_SPEC = Path(__file__).resolve().parent.parent / "samples" / "iot_sensor_node" / "iot_sensor_node.yaml"
_EXAMPLE_SPEC = Path(__file__).resolve().parent.parent / "src" / "circuit_weaver" / "examples" / "iot_sensor.yaml"


def _run(args: list[str], *, timeout: int = 60, cwd: Path | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "circuit_weaver.dispatcher"] + args,
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=str(cwd) if cwd is not None else None,
    )


# ---------- --help for every subcommand ----------


@pytest.mark.parametrize(
    "cmd",
    [
        "validate",
        "apply-patch",
        "generate",
        "diff",
        "ingest-pcb-feedback",
        "list-templates",
        "scaffold",
        "export-jlcpcb",
        "export-gerbers",
        "cost-bom",
        "schema",
        "harvest-specs",
        "extract-specs",
        "fetch-spice",
        "optimize-placement",
        "placement-viewer",
        "si-constraints",
        "thermal-analysis",
        "export-dual-cpl",
        "panelize",
    ],
)
def test_subcommand_help(cmd):
    """Every subcommand should accept --help and exit 0."""
    result = _run([cmd, "--help"])
    assert result.returncode == 0, f"{cmd} --help failed: {result.stderr[:300]}"


# ---------- Commands that work without external deps ----------


def test_validate_example_spec():
    """validate should accept the example spec."""
    if os.environ.get("CI"):
        pytest.skip("Artifact validation requires KiCad CLI (unavailable in CI)")
    result = _run(["validate", str(_EXAMPLE_SPEC)])
    # Exit 0 or 1 (warnings are ok), but shouldn't crash
    assert result.returncode in (0, 1), f"validate crashed: {result.stderr[:500]}"
    # Should produce JSON output
    assert result.stdout.strip(), "validate produced no output"


def test_validate_strict_example():
    """validate --strict should run without crashing."""
    result = _run(["validate", str(_EXAMPLE_SPEC), "--strict"])
    assert result.returncode in (0, 1, 2)  # 2 = strict failures promoted from warnings


def test_list_templates():
    """list-templates should list all templates."""
    result = _run(["list-templates"])
    assert result.returncode == 0
    assert "buck" in result.stdout.lower()


def test_list_templates_json():
    """list-templates --json should produce valid JSON."""
    result = _run(["list-templates", "--json"])
    assert result.returncode == 0
    data = json.loads(result.stdout)
    assert isinstance(data, (list, dict))


def test_scaffold_buck():
    """scaffold --template buck should produce YAML."""
    result = _run(["scaffold", "--template", "buck", "--ref", "U1"])
    assert result.returncode == 0
    assert "buck" in result.stdout.lower() or "U1" in result.stdout


def test_schema_json():
    """schema should produce valid JSON."""
    result = _run(["schema"])
    assert result.returncode == 0
    data = json.loads(result.stdout)
    assert "properties" in data or "type" in data


def test_schema_markdown():
    """schema --format markdown should produce markdown table."""
    result = _run(["schema", "--format", "markdown"])
    assert result.returncode == 0
    assert "Field" in result.stdout or "|" in result.stdout


def test_generate_example(tmp_path):
    """generate should produce KiCad artifacts."""
    out = tmp_path / "gen_out"
    result = _run(["generate", str(_EXAMPLE_SPEC), "--output", str(out), "--no-svg", "--no-require-valid"])
    assert result.returncode == 0, f"generate failed: {result.stderr[:500]}"
    assert (out / "IoT_Sensor.kicad_sch").exists()
    assert not (out / "main.kicad_sch").exists()


def test_generate_no_py_artifacts(tmp_path):
    """generate must not write any .py files to the output directory (Task 113)."""
    project_root = tmp_path / "project_root"
    project_root.mkdir()
    out = project_root / "gen_out"
    result = _run(
        ["generate", str(_EXAMPLE_SPEC), "--output", str(out), "--no-svg", "--no-require-valid"],
        cwd=project_root,
    )
    assert result.returncode == 0, f"generate failed: {result.stderr[:300]}"
    py_files = sorted(path.relative_to(project_root) for path in project_root.rglob("*.py"))
    assert py_files == [], f"Unexpected .py files in output: {py_files}"


def test_generate_log_file(tmp_path):
    """generate should write circuit-weaver.log to the output directory (Task 114)."""
    out = tmp_path / "gen_out"
    result = _run(["generate", str(_EXAMPLE_SPEC), "--output", str(out), "--no-svg", "--no-require-valid"])
    assert result.returncode == 0, f"generate failed: {result.stderr[:300]}"
    log = out / "circuit-weaver.log"
    assert log.exists(), "circuit-weaver.log not created"
    content = log.read_text(encoding="utf-8")
    assert "Allocated" in content, "log missing component allocation entry"
    assert "main: " in content, "log missing per-sheet allocation summary"
    assert "IoT_Sensor.kicad_sch" in content, "log missing generated file path"


def test_generate_schematic_paren_balance(tmp_path):
    """Generated .kicad_sch must have balanced S-expression parentheses (Task 115)."""
    out = tmp_path / "gen_out"
    result = _run(["generate", str(_EXAMPLE_SPEC), "--output", str(out), "--no-svg", "--no-require-valid"])
    assert result.returncode == 0, f"generate failed: {result.stderr[:300]}"
    for sch in out.glob("*.kicad_sch"):
        content = sch.read_text(encoding="utf-8")
        depth = 0
        min_depth = 0
        in_string = False
        escape_next = False
        for ch in content:
            if escape_next:
                escape_next = False
                continue
            if ch == "\\" and in_string:
                escape_next = True
                continue
            if ch == '"':
                in_string = not in_string
                continue
            if in_string:
                continue
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                min_depth = min(min_depth, depth)
        assert depth == 0, f"{sch.name}: unbalanced S-expression (depth={depth})"
        assert min_depth >= 0, f"{sch.name}: encountered unmatched closing paren"


def test_cost_bom_sample():
    """cost-bom should run on sample spec (may fail network lookups)."""
    if not _SAMPLE_SPEC.exists():
        pytest.skip("Sample spec not found")
    result = _run(["cost-bom", str(_SAMPLE_SPEC), "--qty", "1,10", "--json"], timeout=120)
    # Network lookups may fail, but it shouldn't crash
    assert result.returncode in (0, 1)
    if result.returncode == 0:
        data = json.loads(result.stdout)
        assert "rows" in data or "status" in data


def test_export_jlcpcb_sample(tmp_path):
    """export-jlcpcb should produce BOM + CPL files."""
    if not _SAMPLE_SPEC.exists():
        pytest.skip("Sample spec not found")
    out = tmp_path / "jlcpcb"
    result = _run(["export-jlcpcb", str(_SAMPLE_SPEC), "--output", str(out)])
    assert result.returncode == 0, f"export-jlcpcb failed: {result.stderr[:500]}"
    assert (out / "bom_jlcpcb.csv").exists()


def _extract_json(text: str) -> dict:
    """Extract first JSON object from text that may have prefix lines."""
    # Find the first { and parse from there
    idx = text.find("{")
    if idx < 0:
        return json.loads(text)  # Will raise if not valid
    return json.loads(text[idx:])


def test_si_constraints_example():
    """si-constraints should run without crashing."""
    result = _run(["si-constraints", str(_EXAMPLE_SPEC), "--json"])
    assert result.returncode == 0
    data = _extract_json(result.stdout)
    assert "buses_detected" in data


def test_thermal_analysis_example():
    """thermal-analysis should run without crashing."""
    result = _run(["thermal-analysis", str(_EXAMPLE_SPEC), "--json"])
    assert result.returncode == 0
    data = _extract_json(result.stdout)
    assert "total_power_w" in data


def test_optimize_placement_example():
    """optimize-placement should produce placements."""
    result = _run(["optimize-placement", str(_EXAMPLE_SPEC), "--json", "--iterations", "100", "--seed", "42"])
    assert result.returncode == 0
    data = _extract_json(result.stdout)
    assert "placements" in data


def test_panelize():
    """panelize should suggest panel layout."""
    result = _run(["panelize", "--board-width", "50", "--board-height", "40", "--qty", "100", "--json"])
    assert result.returncode == 0
    data = json.loads(result.stdout)
    assert "panel_options" in data
    assert len(data["panel_options"]) >= 1


def test_export_dual_cpl_example(tmp_path):
    """export-dual-cpl should produce top + bottom CPL files."""
    out = tmp_path / "dual_cpl"
    result = _run(["export-dual-cpl", str(_EXAMPLE_SPEC), "--output", str(out)])
    assert result.returncode == 0, f"export-dual-cpl failed: {result.stderr[:500]}"
    assert (out / "cpl_top.csv").exists()
    assert (out / "cpl_bottom.csv").exists()


def test_placement_viewer_example(tmp_path):
    """placement-viewer should generate HTML."""
    out = tmp_path / "viewer.html"
    result = _run(["placement-viewer", str(_EXAMPLE_SPEC), "--output", str(out)])
    assert result.returncode == 0, f"placement-viewer failed: {result.stderr[:500]}"
    assert out.exists()
    content = out.read_text(encoding="utf-8")
    assert "<!DOCTYPE html>" in content


def test_diff_same_spec():
    """diff of a spec against itself should show no changes."""
    result = _run(["diff", str(_EXAMPLE_SPEC), str(_EXAMPLE_SPEC)])
    assert result.returncode == 0
    data = json.loads(result.stdout)
    assert data.get("added_blocks") == [] or len(data.get("added_blocks", [])) == 0
