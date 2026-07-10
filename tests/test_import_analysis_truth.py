"""Truthful analyzer capability and replacement cleanup tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from circuit_weaver import design_import
from circuit_weaver.design_import import import_design
from circuit_weaver.project_state import load_project_state, save_project_state


def test_netlist_only_import_is_explicitly_not_analyzable(tmp_path: Path) -> None:
    source = tmp_path / "netlist"
    project = tmp_path / "project"
    source.mkdir()
    (source / "board.net").write_text("(export (components))", encoding="utf-8")

    result = import_design(source, project_dir=project, analyze=True)

    assert result["analysis_supported"] is False
    assert result["analysis_status"] == "unsupported_netlist_only"
    assert "no bundled netlist analyzer" in result["analysis_reason"]
    assert all("analyze-design" not in action for action in result["next_actions"])
    assert result["analysis"]["status"] == "analysis_unsupported"
    assert result["analysis"]["results"] == {}
    state = load_project_state(project)
    assert state is not None
    assert state.status == "analysis_unsupported"
    assert state.workflow["import"]["analysis_supported"] is False


def _seed_stale_analysis(project: Path) -> tuple[Path, bytes, bytes]:
    analysis = project / ".circuit-weaver" / "analysis"
    analysis.mkdir(parents=True)
    report = analysis / "01_pcb_old.json"
    index = analysis / "index.json"
    report.write_text('{"stale": true}\n', encoding="utf-8")
    index.write_text('{"status": "analyzed"}\n', encoding="utf-8")
    state = load_project_state(project)
    assert state is not None
    state.analyses = {"pcb:old": {"status": "ok", "output": str(report)}}
    state.artifacts.append({"kind": "analysis_index", "path": index.relative_to(project).as_posix()})
    save_project_state(project, state)
    return analysis, report.read_bytes(), index.read_bytes()


def test_force_replacement_removes_stale_analyzer_json_after_commit(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    project = tmp_path / "project"
    first.mkdir()
    second.mkdir()
    (first / "first.kicad_pcb").write_text("(kicad_pcb first)", encoding="utf-8")
    (second / "second.kicad_pcb").write_text("(kicad_pcb second)", encoding="utf-8")
    import_design(first, project_dir=project)
    analysis, _report_bytes, _index_bytes = _seed_stale_analysis(project)

    import_design(second, project_dir=project, force=True)

    assert not analysis.exists()
    assert not list((project / ".circuit-weaver").glob(".analysis.*.backup"))
    state = load_project_state(project)
    assert state is not None
    assert state.analyses == {}
    assert all(record.get("kind") != "analysis_index" for record in state.artifacts)


def test_failed_replacement_commit_restores_quarantined_analysis(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    project = tmp_path / "project"
    first.mkdir()
    second.mkdir()
    (first / "first.kicad_pcb").write_text("(kicad_pcb first)", encoding="utf-8")
    (second / "second.kicad_pcb").write_text("(kicad_pcb second)", encoding="utf-8")
    import_design(first, project_dir=project)
    analysis, report_bytes, index_bytes = _seed_stale_analysis(project)

    def fail_commit(*_args, **_kwargs):
        raise OSError("simulated replacement manifest failure")

    monkeypatch.setattr(design_import, "save_project_state", fail_commit)
    with pytest.raises(OSError, match="replacement manifest failure"):
        import_design(second, project_dir=project, force=True)

    assert (analysis / "01_pcb_old.json").read_bytes() == report_bytes
    assert (analysis / "index.json").read_bytes() == index_bytes
    assert not list((project / ".circuit-weaver").glob(".analysis.*.backup"))

