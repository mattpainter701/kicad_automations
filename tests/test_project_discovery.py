"""Tests for project discovery and auto-detection."""

import json
from pathlib import Path

import pytest

from circuit_weaver.project_discovery import (
    DiscoveredProject,
    detect_project_type,
    discover_projects,
    format_project_table,
    get_project_status,
)


@pytest.fixture
def workspace(tmp_path):
    """Create a workspace with various project types."""
    # Circuit Weaver project (design.yaml)
    cw_proj = tmp_path / "my_sensor"
    cw_proj.mkdir()
    (cw_proj / "design.yaml").write_text("project: My_Sensor\nblocks: []")
    (cw_proj / "design.log").write_text(
        '{"type": "wizard_step", "step": 1, "description": "setup"}\n'
    )

    # KiCad native project (.kicad_pro)
    kicad_proj = tmp_path / "motor_ctrl"
    kicad_proj.mkdir()
    (kicad_proj / "motor_ctrl.kicad_pro").write_text("{}")
    (kicad_proj / "motor_ctrl.kicad_sch").write_text("(kicad_sch)")

    # Mixed project (both design.yaml and .kicad_pro)
    mixed_proj = tmp_path / "usb_bridge"
    mixed_proj.mkdir()
    (mixed_proj / "design.yaml").write_text("project: USB_Bridge\nblocks: []")
    (mixed_proj / "usb_bridge.kicad_pro").write_text("{}")
    (mixed_proj / "usb_bridge.kicad_sch").write_text("(kicad_sch)")

    # Empty directory (no project)
    empty = tmp_path / "random_dir"
    empty.mkdir()

    return tmp_path


class TestDetectProjectType:
    def test_circuit_weaver_project(self, workspace):
        assert detect_project_type(workspace / "my_sensor") == "circuit_weaver"

    def test_kicad_native_project(self, workspace):
        assert detect_project_type(workspace / "motor_ctrl") == "kicad_native"

    def test_mixed_project(self, workspace):
        assert detect_project_type(workspace / "usb_bridge") == "mixed"

    def test_unknown_project(self, workspace):
        assert detect_project_type(workspace / "random_dir") == "unknown"

    def test_kicad_sch_only(self, tmp_path):
        proj = tmp_path / "sch_only"
        proj.mkdir()
        (proj / "test.kicad_sch").write_text("(kicad_sch)")
        assert detect_project_type(proj) == "kicad_native"


class TestDiscoverProjects:
    def test_finds_all_project_types(self, workspace):
        projects = discover_projects(workspace)
        names = {p.name for p in projects}
        assert "my_sensor" in names
        assert "motor_ctrl" in names
        assert "usb_bridge" in names
        assert "random_dir" not in names

    def test_returns_sorted_by_name(self, workspace):
        projects = discover_projects(workspace)
        names = [p.name for p in projects]
        assert names == sorted(names)

    def test_empty_directory(self, tmp_path):
        empty = tmp_path / "empty"
        empty.mkdir()
        assert discover_projects(empty) == []

    def test_nonexistent_directory(self, tmp_path):
        assert discover_projects(tmp_path / "does_not_exist") == []

    def test_depth_limiting(self, tmp_path):
        # Create nested project at depth 3
        nested = tmp_path / "a" / "b" / "c" / "deep_project"
        nested.mkdir(parents=True)
        (nested / "design.yaml").write_text("project: Deep")

        # Depth 2 should not find it
        projects = discover_projects(tmp_path, max_depth=2)
        assert not any(p.name == "deep_project" for p in projects)

    def test_skips_hidden_dirs(self, tmp_path):
        hidden = tmp_path / ".hidden_project"
        hidden.mkdir()
        (hidden / "design.yaml").write_text("project: Hidden")
        projects = discover_projects(tmp_path)
        assert not any(p.name == ".hidden_project" for p in projects)


class TestGetProjectStatus:
    def test_circuit_weaver_project_status(self, workspace):
        status = get_project_status(workspace / "my_sensor")
        assert status.has_design_yaml is True
        assert status.has_design_log is True
        assert status.project_type == "circuit_weaver"
        assert status.status == "in_progress"
        assert status.name == "my_sensor"

    def test_kicad_native_status(self, workspace):
        status = get_project_status(workspace / "motor_ctrl")
        assert status.has_kicad_pro is True
        assert status.has_kicad_sch is True
        assert status.project_type == "kicad_native"

    def test_generated_status(self, workspace):
        proj = workspace / "my_sensor"
        output = proj / "output"
        output.mkdir()
        (output / "main.kicad_sch").write_text("(kicad_sch)")
        status = get_project_status(proj)
        assert status.status == "generated"

    def test_validated_status(self, workspace):
        proj = workspace / "my_sensor"
        log = proj / "design.log"
        log.write_text(
            '{"type": "wizard_step", "step": 1}\n'
            '{"type": "validation", "passed": true}\n'
        )
        status = get_project_status(proj)
        assert status.status == "validated"

    def test_to_dict(self, workspace):
        status = get_project_status(workspace / "my_sensor")
        d = status.to_dict()
        assert isinstance(d, dict)
        assert d["name"] == "my_sensor"
        assert d["has_design_yaml"] is True
        assert isinstance(d["path"], str)


class TestFormatProjectTable:
    def test_format_with_projects(self, workspace):
        projects = discover_projects(workspace)
        table = format_project_table(projects)
        assert "my_sensor" in table
        assert "motor_ctrl" in table
        assert "usb_bridge" in table
        assert "Project" in table  # header

    def test_format_empty(self):
        assert "No circuit projects found" in format_project_table([])


class TestDiscoverCLI:
    def test_discover_cli_json(self, workspace):
        import subprocess

        result = subprocess.run(
            ["python", "-m", "circuit_weaver", "discover", "--root", str(workspace), "--json"],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert isinstance(data, list)
        names = {p["name"] for p in data}
        assert "my_sensor" in names

    def test_discover_cli_table(self, workspace):
        import subprocess

        result = subprocess.run(
            ["python", "-m", "circuit_weaver", "discover", "--root", str(workspace)],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
        assert "my_sensor" in result.stdout
