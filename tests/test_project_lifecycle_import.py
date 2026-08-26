"""Focused recovery tests for durable state and native design imports."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

from circuit_weaver import design_import
from circuit_weaver.design_import import ArchiveLimits, analyze_design, import_design, safe_extract_zip
from circuit_weaver.dispatcher import _handle_design_workflow
from circuit_weaver.finding_model import FINDING_SCHEMA_VERSION
from circuit_weaver.logging_bridge import _resolve_log_dir
from circuit_weaver.project_discovery import detect_project_type, discover_projects, get_project_status
from circuit_weaver.project_state import (
    AmbiguousProjectStateError,
    ProjectState,
    file_sha256,
    get_project_state_summary,
    load_project_state,
    project_state_path,
    record_generation_state,
    resume_project,
    save_project_state,
)


def _write_native_project(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "control.kicad_pro").write_text("{}", encoding="utf-8")
    (root / "control.kicad_sch").write_text(
        '(kicad_sch (version 20231120) (property "Sheetfile" "power.kicad_sch"))',
        encoding="utf-8",
    )
    (root / "power.kicad_sch").write_text("(kicad_sch (version 20231120))", encoding="utf-8")
    (root / "control.kicad_pcb").write_text("(kicad_pcb (version 20240108))", encoding="utf-8")


def test_import_is_non_destructive_and_records_hierarchy(tmp_path: Path) -> None:
    source = tmp_path / "source"
    project = tmp_path / "state"
    _write_native_project(source)
    before = {path.name: file_sha256(path) for path in source.iterdir() if path.is_file()}

    result = import_design(source, project_dir=project)

    after = {path.name: file_sha256(path) for path in source.iterdir() if path.is_file()}
    assert before == after
    assert not (project / "design.yaml").exists()
    assert Path(result["manifest"]).is_file()
    roles = {Path(item["path"]).name: item["role"] for item in result["sources"]}
    assert roles["control.kicad_sch"] == "root_schematic"
    assert roles["power.kicad_sch"] == "child_schematic"
    assert result["kind"] == "imported_kicad"
    summary = get_project_state_summary(project)
    assert summary["inventory"]["schematics"] == 2
    assert summary["inventory"]["pcbs"] == 1


def test_import_single_file_inventories_sibling_project_files(tmp_path: Path) -> None:
    source = tmp_path / "native"
    _write_native_project(source)

    result = import_design(source / "control.kicad_sch")

    kinds = {item["kind"] for item in result["sources"]}
    assert {"kicad_project", "schematic", "pcb"} <= kinds


def test_safe_zip_rejects_traversal_and_removes_staging(tmp_path: Path) -> None:
    archive = tmp_path / "unsafe.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("../escape.kicad_pcb", "bad")
    destination = tmp_path / "extract"

    with pytest.raises(ValueError, match="Unsafe ZIP"):
        safe_extract_zip(archive, destination)

    assert not destination.exists()
    assert not (tmp_path / "escape.kicad_pcb").exists()


def test_safe_zip_enforces_file_and_total_limits(tmp_path: Path) -> None:
    archive = tmp_path / "large.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("a.gbr", "12345")
        bundle.writestr("b.gbr", "67890")

    with pytest.raises(ValueError, match="limit"):
        safe_extract_zip(archive, tmp_path / "extract-count", limits=ArchiveLimits(max_files=1))
    with pytest.raises(ValueError, match="expanded size"):
        safe_extract_zip(
            archive,
            tmp_path / "extract-total",
            limits=ArchiveLimits(max_files=3, max_file_bytes=10, max_total_bytes=6),
        )


def test_safe_zip_never_removes_an_existing_destination(tmp_path: Path) -> None:
    archive = tmp_path / "files.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("board.gbr", "G04*")
    destination = tmp_path / "existing"
    destination.mkdir()
    sentinel = destination / "keep.txt"
    sentinel.write_text("keep", encoding="utf-8")

    with pytest.raises(FileExistsError):
        safe_extract_zip(archive, destination)

    assert sentinel.read_text(encoding="utf-8") == "keep"


@pytest.mark.parametrize(
    "member_name",
    [
        "CON.gbr",
        "nested/NUL.txt",
        "nested/board.gbr:payload",
        "nested/trailing.",
        "nested/trailing ",
    ],
)
def test_safe_zip_rejects_windows_alias_and_stream_names(tmp_path: Path, member_name: str) -> None:
    archive = tmp_path / "unsafe-name.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr(member_name, "bad")
    destination = tmp_path / "extract"

    with pytest.raises(ValueError, match="Unsafe ZIP"):
        safe_extract_zip(archive, destination)

    assert not destination.exists()


def test_zip_import_preserves_archive_and_stages_sources(tmp_path: Path) -> None:
    archive = tmp_path / "fab.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("fab/board-F_Cu.gbr", "G04 copper*")
        bundle.writestr("fab/board.drl", "M48\nM30")
    before = file_sha256(archive)

    result = import_design(archive)

    assert file_sha256(archive) == before
    assert result["kind"] == "imported_gerber"
    assert any(item["kind"] == "source_archive" for item in result["sources"])
    assert project_state_path(Path(result["project_root"])).is_file()


def test_force_zip_replacement_rolls_back_when_candidate_is_invalid(tmp_path: Path) -> None:
    archive = tmp_path / "fab.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("fab/board.gbr", "G04 original*")
    imported = import_design(archive)
    project = Path(imported["project_root"])
    manifest = Path(imported["manifest"])
    prior_manifest = manifest.read_bytes()
    gerber_record = next(item for item in imported["sources"] if item["kind"] == "gerber")
    staged_gerber = project / gerber_record["path"]

    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("../escape.gbr", "G04 replacement*")

    with pytest.raises(ValueError, match="Unsafe ZIP"):
        import_design(archive, force=True)

    assert staged_gerber.read_text(encoding="utf-8") == "G04 original*"
    assert manifest.read_bytes() == prior_manifest
    imports_dir = project / ".circuit-weaver" / "imports"
    assert not [path for path in imports_dir.iterdir() if path.name.endswith((".staging", ".backup"))]


def test_force_zip_replacement_rolls_back_when_manifest_commit_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    archive = tmp_path / "fab.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("fab/board.gbr", "G04 original*")
    imported = import_design(archive)
    project = Path(imported["project_root"])
    gerber_record = next(item for item in imported["sources"] if item["kind"] == "gerber")
    staged_gerber = project / gerber_record["path"]
    prior_manifest = Path(imported["manifest"]).read_bytes()

    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("fab/board.gbr", "G04 valid replacement*")

    def fail_commit(*_args, **_kwargs):
        raise OSError("simulated manifest commit failure")

    monkeypatch.setattr(design_import, "save_project_state", fail_commit)
    with pytest.raises(OSError, match="manifest commit failure"):
        import_design(archive, force=True)

    assert staged_gerber.read_text(encoding="utf-8") == "G04 original*"
    assert Path(imported["manifest"]).read_bytes() == prior_manifest
    imports_dir = project / ".circuit-weaver" / "imports"
    assert not [path for path in imports_dir.iterdir() if path.name.endswith((".staging", ".backup"))]


def test_different_import_requires_force_and_invalidates_stale_analysis(tmp_path: Path) -> None:
    first_source = tmp_path / "first"
    second_source = tmp_path / "second"
    project = tmp_path / "project"
    first_source.mkdir()
    second_source.mkdir()
    (first_source / "first.kicad_pcb").write_text("(kicad_pcb first)", encoding="utf-8")
    (second_source / "second.kicad_pcb").write_text("(kicad_pcb second)", encoding="utf-8")
    import_design(first_source, project_dir=project)

    state = load_project_state(project)
    assert state is not None
    prior_import = dict(state.workflow["import"])
    state.workflow["generate"] = {"status": "generated", "completed_at": "earlier"}
    state.analyses = {"pcb:first": {"status": "ok", "output": "old.json"}}
    state.artifacts.append({"kind": "analysis_index", "path": "old-index.json"})
    save_project_state(project, state)

    with pytest.raises(ValueError, match="--force"):
        import_design(second_source, project_dir=project)

    unchanged = load_project_state(project)
    assert unchanged is not None
    assert unchanged.analyses == state.analyses
    assert unchanged.workflow["import"] == prior_import

    import_design(second_source, project_dir=project, force=True)
    replaced = load_project_state(project)
    assert replaced is not None
    assert replaced.analyses == {}
    assert replaced.workflow["generate"]["status"] == "generated"
    assert replaced.workflow["import_history"][-1] == prior_import
    assert all(item.get("kind") != "analysis_index" for item in replaced.artifacts)
    assert {Path(item["path"]).name for item in replaced.sources} == {"second.kicad_pcb"}


def test_analyze_persists_results_and_reuses_matching_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = tmp_path / "native"
    project = tmp_path / "project"
    _write_native_project(source)
    import_design(source, project_dir=project)
    calls: list[str] = []

    def fake_run(script_name: str, input_path: Path, output_path: Path, *, timeout: float):
        calls.append(script_name)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps({"input": str(input_path)}), encoding="utf-8")
        return {
            "status": "ok",
            "input": str(input_path),
            "output": str(output_path),
            "script": script_name,
        }

    monkeypatch.setattr(design_import, "_run_analyzer", fake_run)
    first = analyze_design(project)
    first_call_count = len(calls)
    second = analyze_design(project)

    assert first["status"] == "analyzed"
    assert first_call_count == 2  # root schematic + PCB
    assert len(calls) == first_call_count
    assert all(entry["cached"] for entry in second["results"].values())
    summary = get_project_state_summary(project)
    assert summary["status"] == "analyzed"
    assert Path(first["analysis_index"]).is_file()


def test_analyze_exports_normalized_findings_as_json_and_sarif(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "native"
    project = tmp_path / "project"
    _write_native_project(source)
    import_design(source, project_dir=project)

    def fake_run(script_name: str, input_path: Path, output_path: Path, *, timeout: float):
        payload: dict[str, object] = {"input": str(input_path)}
        if script_name == "analyze_pcb.py":
            payload["dfm"] = {
                "violations": [
                    {
                        "parameter": "track_width",
                        "actual_mm": 0.08,
                        "tier_required": "challenging",
                        "message": "Minimum track width is 0.08 mm",
                    }
                ]
            }
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(payload), encoding="utf-8")
        return {
            "status": "ok",
            "input": str(input_path),
            "output": str(output_path),
            "script": script_name,
        }

    monkeypatch.setattr(design_import, "_run_analyzer", fake_run)
    result = analyze_design(project)

    findings = json.loads(Path(result["findings_json"]).read_text(encoding="utf-8"))
    sarif = json.loads(Path(result["findings_sarif"]).read_text(encoding="utf-8"))
    index = json.loads(Path(result["analysis_index"]).read_text(encoding="utf-8"))
    assert findings["schema_version"] == FINDING_SCHEMA_VERSION
    assert findings["finding_count"] == 1
    finding = findings["findings"][0]
    assert finding["rule_id"] == "CW-DFM-001"
    assert finding["location"]["artifact_path"].endswith("/control.kicad_pcb")
    assert not Path(finding["location"]["artifact_path"]).is_absolute()
    assert sarif["runs"][0]["results"][0]["partialFingerprints"] == {
        "circuitWeaverFindingId/v1": finding["id"]
    }
    assert index["finding_exports"]["finding_count"] == 1
    persisted = load_project_state(project)
    assert persisted is not None
    assert {item["kind"] for item in persisted.artifacts} >= {
        "analysis_findings_json",
        "analysis_findings_sarif",
    }


def test_analysis_cache_rehashes_live_sources(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = tmp_path / "native"
    project = tmp_path / "project"
    _write_native_project(source)
    import_design(source, project_dir=project)
    calls: list[str] = []

    def fake_run(script_name: str, input_path: Path, output_path: Path, *, timeout: float):
        calls.append(script_name)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps({"input": str(input_path)}), encoding="utf-8")
        return {"status": "ok", "input": str(input_path), "output": str(output_path), "script": script_name}

    monkeypatch.setattr(design_import, "_run_analyzer", fake_run)
    analyze_design(project)
    initial_calls = len(calls)
    assert initial_calls == 2
    assert all(entry["cached"] for entry in analyze_design(project)["results"].values())

    board = source / "control.kicad_pcb"
    board.write_text("(kicad_pcb (version 20240109))", encoding="utf-8")
    refreshed = analyze_design(project)

    assert len(calls) == initial_calls + 1
    pcb_entry = next(entry for key, entry in refreshed["results"].items() if key.startswith("pcb:"))
    assert pcb_entry["cached"] is False
    persisted = load_project_state(project)
    assert persisted is not None
    board_record = next(item for item in persisted.sources if item.get("kind") == "pcb")
    assert board_record["sha256"] == file_sha256(board)


def test_paste_gerber_is_inventoried_reconciled_and_invalidates_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "gerbers"
    project = tmp_path / "project"
    source.mkdir()
    (source / "board.gtl").write_text("copper-v1", encoding="utf-8")
    paste = source / "board.gtp"
    paste.write_text("paste-v1", encoding="utf-8")

    imported = import_design(source, project_dir=project)
    paste_record = next(item for item in imported["sources"] if Path(item["path"]).suffix == ".gtp")
    assert paste_record["kind"] == "gerber"
    assert paste_record["sha256"] == file_sha256(paste)
    assert get_project_state_summary(project)["inventory"]["gerber_files"] == 2

    calls: list[str] = []

    def fake_run(script_name: str, input_path: Path, output_path: Path, *, timeout: float):
        calls.append(script_name)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps({"input": str(input_path)}), encoding="utf-8")
        return {
            "status": "ok",
            "input": str(input_path),
            "output": str(output_path),
            "script": script_name,
        }

    monkeypatch.setattr(design_import, "_run_analyzer", fake_run)
    analyze_design(project)
    assert calls == ["analyze_gerbers.py"]
    assert all(entry["cached"] for entry in analyze_design(project)["results"].values())

    # Keep the file size constant so both reconciliation and cache invalidation
    # are proven to depend on the content hash, not merely stat size.
    paste.write_text("paste-v2", encoding="utf-8")
    changed = get_project_state_summary(project)
    assert changed["status"] == "source_changed"
    changed_paste = next(
        item for item in changed["reconciliation"]["sources"] if Path(item["path"]).suffix == ".gtp"
    )
    assert changed_paste["status"] == "modified"

    refreshed = analyze_design(project)
    assert calls == ["analyze_gerbers.py", "analyze_gerbers.py"]
    assert next(iter(refreshed["results"].values()))["cached"] is False
    persisted = load_project_state(project)
    assert persisted is not None
    persisted_paste = next(
        item for item in persisted.sources if Path(item["path"]).suffix == ".gtp"
    )
    assert persisted_paste["sha256"] == file_sha256(paste)


def test_standard_protel_paste_internal_and_drill_files_share_one_inventory_policy(
    tmp_path: Path,
) -> None:
    source = tmp_path / "fab"
    project = tmp_path / "project"
    source.mkdir()
    expected_kinds = {
        "top.gtp": "gerber",
        "bottom.gbp": "gerber",
        "inner.g1": "gerber",
        "plane.gp2": "gerber",
        "mechanical.gm2": "gerber",
        "holes.drl": "drill",
    }
    for filename in expected_kinds:
        (source / filename).write_text("G04 artwork*", encoding="utf-8")

    imported = import_design(source, project_dir=project)

    assert {Path(item["path"]).name: item["kind"] for item in imported["sources"]} == expected_kinds
    assert get_project_state_summary(project)["inventory"]["gerber_files"] == len(expected_kinds)


def test_analysis_cache_invalidates_when_analyzer_fingerprint_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "native"
    project = tmp_path / "project"
    _write_native_project(source)
    import_design(source, project_dir=project)
    calls: list[str] = []
    analyzer_version = {"value": "v1"}

    def fake_run(script_name: str, input_path: Path, output_path: Path, *, timeout: float):
        calls.append(script_name)
        output_path.write_text(json.dumps({"input": str(input_path)}), encoding="utf-8")
        return {"status": "ok", "input": str(input_path), "output": str(output_path), "script": script_name}

    monkeypatch.setattr(design_import, "_run_analyzer", fake_run)
    monkeypatch.setattr(
        design_import,
        "_analyzer_fingerprint",
        lambda script_name: f"{script_name}:{analyzer_version['value']}",
    )
    analyze_design(project)
    initial_calls = len(calls)
    assert all(entry["cached"] for entry in analyze_design(project)["results"].values())

    analyzer_version["value"] = "v2"
    refreshed = analyze_design(project)

    assert len(calls) == initial_calls * 2
    assert all(not entry["cached"] for entry in refreshed["results"].values())


def test_cached_analysis_requires_matching_hash_and_json_object(tmp_path: Path) -> None:
    output = tmp_path / "analysis.json"
    output.write_text('{"ok": true}', encoding="utf-8")
    source_fingerprint = "source-v1"
    analyzer_fingerprint = "analyzer-v1"
    prior = {
        "status": "ok",
        "source_fingerprint": source_fingerprint,
        "analyzer_fingerprint": analyzer_fingerprint,
        "output": str(output),
        "output_sha256": file_sha256(output),
    }

    assert design_import._cached_analysis_is_valid(
        prior,
        root=tmp_path,
        source_fingerprint=source_fingerprint,
        analyzer_fingerprint=analyzer_fingerprint,
    )

    output.write_text('{"tampered": true}', encoding="utf-8")
    assert not design_import._cached_analysis_is_valid(
        prior,
        root=tmp_path,
        source_fingerprint=source_fingerprint,
        analyzer_fingerprint=analyzer_fingerprint,
    )

    output.write_text("[]", encoding="utf-8")
    prior["output_sha256"] = file_sha256(output)
    assert not design_import._cached_analysis_is_valid(
        prior,
        root=tmp_path,
        source_fingerprint=source_fingerprint,
        analyzer_fingerprint=analyzer_fingerprint,
    )


def test_analyzer_failure_is_restartable_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project = tmp_path / "project"
    _write_native_project(project)
    import_design(project, project_dir=project)

    def fail(*_args, **_kwargs):
        raise TimeoutError("timed out")

    monkeypatch.setattr(design_import, "_run_analyzer", fail)
    result = analyze_design(project, force=True)

    assert result["status"] == "analysis_failed"
    summary = get_project_state_summary(project)
    assert summary["status"] == "analysis_failed"
    assert "timed out" in summary["last_error"]
    assert "--force" in summary["next_actions"][0]


def test_bundled_gerber_analyzer_runs_through_resource_wrapper(tmp_path: Path) -> None:
    source = tmp_path / "gerbers"
    project = tmp_path / "project"
    source.mkdir()
    (source / "board-F_Cu.gbr").write_text(
        "%FSLAX46Y46*%\n%MOMM*%\n%TF.FileFunction,Copper,L1,Top*%\n"
        "%ADD10C,0.200*%\nD10*\nX0Y0D02*\nX1000000Y1000000D01*\nM02*\n",
        encoding="utf-8",
    )
    import_design(source, project_dir=project)

    result = analyze_design(project, timeout=30)

    assert result["status"] == "analyzed"
    entry = next(iter(result["results"].values()))
    assert entry["script"] == "analyze_gerbers.py"
    assert Path(entry["output"]).is_file()


def test_analyzer_materializes_complete_non_filesystem_resource_tree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    resource_zip = tmp_path / "resources.zip"
    analyzer_source = '''
import argparse
import json
from pathlib import Path
import sexp_parser

parser = argparse.ArgumentParser()
parser.add_argument("input")
parser.add_argument("--output", required=True)
parser.add_argument("--compact", action="store_true")
args = parser.parse_args()
Path(args.output).write_text(json.dumps({"value": sexp_parser.VALUE}), encoding="utf-8")
'''
    with zipfile.ZipFile(resource_zip, "w") as bundle:
        bundle.writestr("scripts/analyze_test.py", analyzer_source)
        bundle.writestr("scripts/sexp_parser.py", "VALUE = 42\n")

    input_path = tmp_path / "input.kicad_pcb"
    output_path = tmp_path / "output.json"
    input_path.write_text("(kicad_pcb)", encoding="utf-8")
    with zipfile.ZipFile(resource_zip) as bundle:
        resource_root = zipfile.Path(bundle, at="scripts/")
        monkeypatch.setattr(design_import, "_bundled_scripts_resource", lambda: resource_root)
        result = design_import._run_analyzer(
            "analyze_test.py",
            input_path,
            output_path,
            timeout=30,
        )

    assert json.loads(output_path.read_text(encoding="utf-8")) == {"value": 42}
    assert result["output_sha256"] == file_sha256(output_path)
    assert result["analyzer_fingerprint"]


def test_discovery_finds_root_pcb_only_and_gerber_only(tmp_path: Path) -> None:
    pcb = tmp_path / "pcb-only"
    pcb.mkdir()
    (pcb / "board.kicad_pcb").write_text("(kicad_pcb)", encoding="utf-8")
    gerber = tmp_path / "gerber-only"
    gerber.mkdir()
    (gerber / "board-F_Cu.gbr").write_text("G04*", encoding="utf-8")

    projects = discover_projects(tmp_path)

    assert {project.name for project in projects} == {"pcb-only", "gerber-only"}
    assert detect_project_type(pcb) == "kicad_native"
    assert detect_project_type(gerber) == "gerber_native"
    assert discover_projects(pcb)[0].path == pcb.resolve()
    assert get_project_status(gerber).has_gerbers is True


@pytest.mark.parametrize("extension", [".gtp", ".gbp", ".g1", ".gp2", ".gm2", ".drl"])
def test_discovery_uses_shared_manufacturing_artwork_policy(
    tmp_path: Path, extension: str
) -> None:
    project = tmp_path / extension.removeprefix(".")
    project.mkdir()
    (project / f"board{extension}").write_text("G04 artwork*", encoding="utf-8")

    discovered = discover_projects(project)

    assert detect_project_type(project) == "gerber_native"
    assert len(discovered) == 1
    assert discovered[0].has_gerbers is True
    assert discovered[0].project_type == "gerber_native"


def test_validation_survives_later_cli_end_marker(tmp_path: Path) -> None:
    project = tmp_path / "legacy"
    project.mkdir()
    (project / "design.yaml").write_text("project: Legacy\nblocks: []\n", encoding="utf-8")
    entries = [
        {"type": "validation", "scope": "final_report", "passed": True, "error_count": 0},
        {"type": "wizard_step", "step": 0, "description": "[validate:end] CLI exited"},
    ]
    (project / "design.log").write_text(
        "".join(json.dumps(entry) + "\n" for entry in entries), encoding="utf-8"
    )

    summary = get_project_state_summary(project)

    assert summary["status"] == "validated"
    assert summary["validation"]["passed"] is True


def test_log_root_prefers_spec_over_output(tmp_path: Path) -> None:
    project = tmp_path / "project"
    output = project / "output"
    project.mkdir()
    spec = project / "design.yaml"
    spec.write_text("project: Test\n", encoding="utf-8")
    args = argparse.Namespace(spec=str(spec), output=str(output))

    assert _resolve_log_dir("generate", args) == project.resolve()


def test_log_root_uses_output_for_standalone_spec_without_project_marker(tmp_path: Path) -> None:
    source = tmp_path / "samples"
    output = tmp_path / "run" / "output"
    source.mkdir()
    spec = source / "example.yaml"
    spec.write_text("project: Example\n", encoding="utf-8")
    args = argparse.Namespace(spec=str(spec), output=str(output))

    assert _resolve_log_dir("generate", args) == output.resolve()


def test_log_root_walks_from_output_board_to_manifest(tmp_path: Path) -> None:
    project = tmp_path / "project"
    output = project / "output"
    output.mkdir(parents=True)
    board = output / "board.kicad_pcb"
    board.write_text("(kicad_pcb)", encoding="utf-8")
    save_project_state(project, ProjectState(name="board"))

    args = argparse.Namespace(kicad_pcb=str(board), output=str(output / "routed.kicad_pcb"))
    assert _resolve_log_dir("autoroute", args) == project.resolve()


def test_resume_native_project_offers_import_instead_of_yaml_generation(tmp_path: Path) -> None:
    project = tmp_path / "native"
    _write_native_project(project)

    result = resume_project(project)

    assert result["resumable"] is True
    assert result["kind"] == "kicad_native"
    assert result["next_actions"][0].startswith("circuit-weaver import-design")


def test_design_wizard_resume_prints_actionable_state_not_placeholder(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    project = tmp_path / "design"
    project.mkdir()
    spec = project / "design.yaml"
    spec.write_text("project: ResumeMe\nblocks: []\n", encoding="utf-8")

    _handle_design_workflow(resume=str(spec), dry_run=True)
    output = capsys.readouterr().out

    assert "Next actions:" in output
    assert "Full implementation in future sprints" not in output


def test_cli_import_then_status_json_round_trip(tmp_path: Path) -> None:
    source = tmp_path / "native"
    project = tmp_path / "state"
    source.mkdir()
    (source / "board.kicad_pcb").write_text("(kicad_pcb)", encoding="utf-8")

    imported = subprocess.run(
        [
            sys.executable,
            "-m",
            "circuit_weaver",
            "import-design",
            str(source),
            "--project-dir",
            str(project),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert imported.returncode == 0, imported.stderr
    imported_payload = json.loads(imported.stdout)

    status = subprocess.run(
        [sys.executable, "-m", "circuit_weaver", "status", str(project), "--json"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert status.returncode == 0, status.stderr
    status_payload = json.loads(status.stdout)
    assert status_payload["project_id"] == imported_payload["project_id"]
    assert status_payload["status"] == "imported"


def test_status_and_resume_find_child_output_state_from_original_spec(tmp_path: Path) -> None:
    project = tmp_path / "standalone"
    output = project / "build" / "output"
    output.mkdir(parents=True)
    spec = project / "iot_sensor_node.yaml"
    spec.write_text("project: LocatorBoard\nblocks: []\n", encoding="utf-8")
    schematic = output / "LocatorBoard.kicad_sch"
    schematic.write_text("(kicad_sch)", encoding="utf-8")
    placement = output / "placement_result.json"
    placement.write_text('{"status": "review_required"}', encoding="utf-8")

    manifest = record_generation_state(
        output,
        project_name="LocatorBoard",
        spec_path=spec,
        output_dir=output,
        phase="generated",
        artifacts=[schematic, placement],
        placement_review=placement,
    )
    expected = load_project_state(output)
    assert expected is not None
    assert manifest == project_state_path(output)

    for target in (spec, project):
        summary = get_project_state_summary(target)
        resumed = resume_project(target)
        assert summary["project_root"] == str(output.resolve())
        assert summary["project_id"] == expected.project_id
        assert summary["kind"] == "circuit_weaver"
        assert summary["status"] == "generated"
        assert summary["current_phase"] == "placement_review"
        assert summary["next_actions"] == expected.next_actions
        assert resumed["project_id"] == expected.project_id
        assert resumed["current_phase"] == "placement_review"
        assert resumed["next_actions"] == expected.next_actions

    for command in ("status", "resume"):
        completed = subprocess.run(
            [sys.executable, "-m", "circuit_weaver", command, str(spec), "--json"],
            capture_output=True,
            text=True,
            check=False,
        )
        assert completed.returncode == 0, completed.stderr
        payload = json.loads(completed.stdout)
        assert payload["project_root"] == str(output.resolve())
        assert payload["project_id"] == expected.project_id
        assert payload["status"] == "generated"
        assert payload["current_phase"] == "placement_review"
        assert payload["next_actions"] == expected.next_actions
        if command == "resume":
            assert payload["resumable"] is True


def test_parent_state_lookup_rejects_ambiguous_generated_children(tmp_path: Path) -> None:
    project = tmp_path / "ambiguous"
    project.mkdir()
    for name in ("alpha", "beta"):
        spec = project / f"{name}.yaml"
        spec.write_text(f"project: {name}\nblocks: []\n", encoding="utf-8")
        output = project / f"{name}-output"
        output.mkdir()
        schematic = output / f"{name}.kicad_sch"
        schematic.write_text("(kicad_sch)", encoding="utf-8")
        record_generation_state(
            output,
            project_name=name,
            spec_path=spec,
            output_dir=output,
            phase="generated",
            artifacts=[schematic],
        )

    alpha = get_project_state_summary(project / "alpha.yaml")
    assert Path(alpha["project_root"]).name == "alpha-output"
    with pytest.raises(AmbiguousProjectStateError, match="Multiple Circuit Weaver project states"):
        get_project_state_summary(project)


def test_status_does_not_select_unrelated_sole_child_manifest(tmp_path: Path) -> None:
    project = tmp_path / "neighbors"
    project.mkdir()
    source = project / "alpha.yaml"
    source.write_text("project: alpha\nblocks: []\n", encoding="utf-8")
    output = project / "unrelated-output"
    output.mkdir()
    schematic = output / "alpha.kicad_sch"
    schematic.write_text("(kicad_sch)", encoding="utf-8")
    record_generation_state(
        output,
        project_name="alpha",
        spec_path=source,
        output_dir=output,
        phase="generated",
        artifacts=[schematic],
    )
    unrelated_state = load_project_state(output)
    assert unrelated_state is not None
    unrelated = project / "victim.kicad_pcb"
    unrelated.write_text("(kicad_pcb)", encoding="utf-8")

    summary = get_project_state_summary(unrelated)

    assert summary["project_root"] == str(project.resolve())
    assert summary["project_id"] != unrelated_state.project_id


def test_generation_state_records_source_artifacts_and_placement_phase(tmp_path: Path) -> None:
    project = tmp_path / "generated"
    output = project / "output"
    output.mkdir(parents=True)
    spec = project / "design.yaml"
    spec.write_text("project: Durable\nblocks: []\n", encoding="utf-8")
    schematic = output / "Durable.kicad_sch"
    schematic.write_text("(kicad_sch)", encoding="utf-8")
    validation = output / "validation_report.json"
    validation.write_text(json.dumps({"valid": True}), encoding="utf-8")
    placement = output / "placement_result.json"
    placement.write_text(json.dumps({"status": "review_required"}), encoding="utf-8")

    record_generation_state(
        output,
        project_name="Durable",
        spec_path=spec,
        output_dir=output,
        phase="running",
    )
    manifest = record_generation_state(
        output,
        project_name="Durable",
        spec_path=spec,
        output_dir=output,
        phase="generated",
        artifacts=[schematic, validation, placement],
        validation_report=validation,
        placement_review=placement,
    )

    assert manifest == project_state_path(project)
    state = load_project_state(project)
    assert state is not None
    assert state.status == "generated"
    assert state.current_phase == "placement_review"
    assert state.workflow["generate"]["validation_valid"] is True
    assert state.sources[0]["path"] == "design.yaml"
    assert {item["path"] for item in state.artifacts} == {
        "output/Durable.kicad_sch",
        "output/placement_result.json",
        "output/validation_report.json",
    }
    assert state.next_actions[0] == "Review output/placement_result.json"


def test_append_only_generation_logs_remain_truthful_nonblocking_artifacts(tmp_path: Path) -> None:
    project = tmp_path / "generated"
    output = project / "output"
    output.mkdir(parents=True)
    spec = project / "design.yaml"
    spec.write_text("project: Durable\nblocks: []\n", encoding="utf-8")
    schematic = output / "Durable.kicad_sch"
    schematic.write_text("(kicad_sch)", encoding="utf-8")
    design_log = project / "design.log"
    design_log.write_text(
        json.dumps({"type": "validation", "scope": "final_report", "passed": True}) + "\n",
        encoding="utf-8",
    )
    text_log = project / "circuit-weaver.log"
    text_log.write_text("generation completed\n", encoding="utf-8")

    record_generation_state(
        output,
        project_name="Durable",
        spec_path=spec,
        output_dir=output,
        phase="generated",
        artifacts=[schematic, design_log, text_log],
    )
    with design_log.open("a", encoding="utf-8") as handle:
        handle.write(
            json.dumps({"type": "wizard_step", "description": "[status:end] CLI exited"}) + "\n"
        )
    with text_log.open("a", encoding="utf-8") as handle:
        handle.write("resume inspected state\n")

    summary = get_project_state_summary(project)
    resumed = resume_project(project)

    assert summary["status"] == "generated"
    assert resumed["status"] == "generated"
    assert summary["reconciliation"]["dirty"] is False
    logs = [
        item
        for item in summary["reconciliation"]["artifacts"]
        if item["kind"] == "generation_log"
    ]
    assert len(logs) == 2
    assert {item["status"] for item in logs} == {"appended"}
    assert all(item["mutable"] and not item["blocking"] for item in logs)
    assert summary["reconciliation"]["summary"]["appended"] == 2


def test_generated_placement_state_takes_precedence_over_prior_validation_log(
    tmp_path: Path,
) -> None:
    project = tmp_path / "generated"
    output = project / "output"
    output.mkdir(parents=True)
    spec = project / "design.yaml"
    spec.write_text("project: PlacementReview\nblocks: []\n", encoding="utf-8")
    schematic = output / "PlacementReview.kicad_sch"
    schematic.write_text("(kicad_sch)", encoding="utf-8")
    placement = output / "placement_result.json"
    placement.write_text('{"status": "review_required"}', encoding="utf-8")
    (project / "design.log").write_text(
        json.dumps({"type": "validation", "scope": "final_report", "passed": True}) + "\n",
        encoding="utf-8",
    )
    record_generation_state(
        output,
        project_name="PlacementReview",
        spec_path=spec,
        output_dir=output,
        phase="generated",
        artifacts=[schematic, placement],
        placement_review=placement,
    )

    raw = load_project_state(project)
    summary = get_project_state_summary(project)

    assert raw is not None
    assert raw.status == "generated"
    assert raw.current_phase == "placement_review"
    assert summary["validation"]["passed"] is True
    assert summary["status"] == "generated"
    assert summary["current_phase"] == "placement_review"


def test_failed_generation_remains_failed_even_with_partial_artifacts(tmp_path: Path) -> None:
    project = tmp_path / "failed"
    output = project / "output"
    output.mkdir(parents=True)
    spec = project / "design.yaml"
    spec.write_text("project: Failed\nblocks: []\n", encoding="utf-8")
    (output / "partial.kicad_sch").write_text("(kicad_sch)", encoding="utf-8")

    record_generation_state(
        output,
        project_name="Failed",
        spec_path=spec,
        output_dir=output,
        phase="failed",
        error="generation stopped after schematic write",
    )
    summary = get_project_state_summary(project)

    assert summary["status"] == "generation_failed"
    assert summary["last_error"] == "generation stopped after schematic write"
    assert summary["next_actions"][0].startswith("circuit-weaver generate")


def test_status_detects_modified_import_source_and_invalidates_analysis_actions(tmp_path: Path) -> None:
    source = tmp_path / "native"
    project = tmp_path / "state"
    _write_native_project(source)
    import_design(source, project_dir=project)

    (source / "control.kicad_pcb").write_text("(kicad_pcb (changed yes))", encoding="utf-8")
    summary = get_project_state_summary(project)

    assert summary["status"] == "source_changed"
    assert summary["reconciliation"]["dirty"] is True
    assert summary["reconciliation"]["summary"]["modified"] == 1
    assert summary["next_actions"] == [f'circuit-weaver analyze-design "{project.resolve()}" --force']


def test_status_detects_missing_generated_artifact_and_offers_regeneration(tmp_path: Path) -> None:
    project = tmp_path / "generated"
    output = project / "output"
    output.mkdir(parents=True)
    spec = project / "design.yaml"
    spec.write_text("project: MissingArtifact\nblocks: []\n", encoding="utf-8")
    artifact = output / "MissingArtifact.kicad_sch"
    artifact.write_text("(kicad_sch)", encoding="utf-8")
    record_generation_state(
        output,
        project_name="MissingArtifact",
        spec_path=spec,
        output_dir=output,
        phase="generated",
        artifacts=[artifact],
    )
    artifact.unlink()

    summary = get_project_state_summary(project)

    assert summary["status"] == "artifacts_missing"
    assert summary["reconciliation"]["summary"]["missing"] == 1
    assert summary["next_actions"][0] == (
        f'circuit-weaver generate "{spec.resolve()}" -o "{output.resolve()}"'
    )
