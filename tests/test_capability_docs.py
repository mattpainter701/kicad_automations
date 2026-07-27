"""Tests for the generated README capability contract."""

from __future__ import annotations

import importlib.util
from pathlib import Path

from circuit_weaver.capabilities import CAPABILITIES

REPO_ROOT = Path(__file__).parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "gen_capability_docs.py"


def _generator_module():
    spec = importlib.util.spec_from_file_location("gen_capability_docs", SCRIPT_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_readme_capability_contract_is_generated_and_current():
    assert _generator_module().update_readme(check=True)


def test_check_detects_readme_drift(tmp_path):
    generator = _generator_module()
    readme = tmp_path / "README.md"
    readme.write_text(
        f"Before\n{generator.START_MARKER}\nold\n{generator.END_MARKER}\nAfter\n",
        encoding="utf-8",
    )

    assert not generator.update_readme(readme)
    assert generator.update_readme(readme, check=True)
    drifted = readme.read_text(encoding="utf-8").replace("Capability Contract", "Drifted Contract")
    readme.write_text(drifted, encoding="utf-8")
    assert not generator.update_readme(readme, check=True)


def test_rendered_contract_lists_every_capability_and_marks_operational_entries():
    rendered = _generator_module().render_capability_table()

    assert rendered.count("| CLI capability |") == 1
    assert rendered.count("not applicable (operational)") == sum(
        record["verification_prereq"] == "not_applicable" for record in CAPABILITIES
    )
    for record in CAPABILITIES:
        assert f"`{record['surfaces']['cli']}`" in rendered
