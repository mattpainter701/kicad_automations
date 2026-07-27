"""Distribution-level contracts that must hold for every PyPI release."""

from __future__ import annotations

from importlib import resources
from importlib.metadata import entry_points, metadata, version
from pathlib import Path

import circuit_weaver
from circuit_weaver.project_spec import _parse_yaml


def test_distribution_version_and_core_dependencies() -> None:
    package_metadata = metadata("circuit-weaver")
    requirements = package_metadata.get_all("Requires-Dist") or []

    assert version("circuit-weaver") == circuit_weaver.__version__ == "0.33.0"
    assert any(
        requirement.lower().startswith("pyyaml") and "extra ==" not in requirement
        for requirement in requirements
    )


def test_distribution_exposes_supported_extras_and_commands() -> None:
    package_metadata = metadata("circuit-weaver")
    requirements = [requirement.lower() for requirement in package_metadata.get_all("Requires-Dist") or []]
    extras = set(package_metadata.get_all("Provides-Extra") or [])
    commands = {entry_point.name for entry_point in entry_points(group="console_scripts")}

    assert {"api", "mcp", "yaml", "lookup", "pdf", "test", "dev", "all"} <= extras
    assert any(requirement.startswith("mcp") and 'extra == "mcp"' in requirement for requirement in requirements)
    assert any(requirement.startswith("fastapi") and 'extra == "api"' in requirement for requirement in requirements)
    assert {"circuit-weaver", "circuit-weaver-mcp"} <= commands


def test_default_install_parses_nested_yaml(tmp_path: Path) -> None:
    spec_path = tmp_path / "design.yaml"
    spec_path.write_text(
        """\
metadata:
  project: nested-yaml-contract
blocks:
  - id: U1
    type: mcu
    params:
      interfaces:
        i2c:
          enabled: true
""",
        encoding="utf-8",
    )

    parsed = _parse_yaml(spec_path)

    assert parsed["blocks"][0]["params"]["interfaces"]["i2c"]["enabled"] is True


def test_distribution_includes_packaged_iot_example() -> None:
    example = resources.files("circuit_weaver").joinpath("examples", "iot_sensor.yaml")

    assert example.is_file()
    with resources.as_file(example) as example_path:
        parsed = _parse_yaml(example_path)

    assert parsed["project"] == "IoT_Sensor"
    assert parsed["power"]


def test_release_workflow_rejects_tag_version_mismatch() -> None:
    release_workflow = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "release.yml"
    workflow_text = release_workflow.read_text(encoding="utf-8")

    assert "GITHUB_REF_NAME" in workflow_text
    assert "Tag/version mismatch" in workflow_text
    assert "twine check" in workflow_text
    assert 'kicad-major: ["8", "9", "10"]' in workflow_text
    assert "circuit_weaver/examples/iot_sensor.yaml" in workflow_text
    assert "__pycache__" in workflow_text


def test_kicad_workflows_initialize_official_footprint_table_before_generation() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    source_table = "/usr/share/kicad/template/fp-lib-table"
    configured_table = '"$HOME/.config/kicad/${{ matrix.kicad-major }}.0/fp-lib-table"'

    for workflow_name in ("ci.yml", "release.yml"):
        workflow = repo_root / ".github" / "workflows" / workflow_name
        workflow_text = workflow.read_text(encoding="utf-8")

        assert f"test -s {source_table}" in workflow_text
        install_at = workflow_text.index("install -D --mode=0644")
        source_at = workflow_text.index(source_table, install_at)
        configured_at = workflow_text.index(configured_table, source_at)
        generate_at = workflow_text.index("python -m circuit_weaver generate")

        assert install_at < source_at < configured_at < generate_at
