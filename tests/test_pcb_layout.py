import hashlib
from dataclasses import replace
from pathlib import Path

import pytest

from circuit_weaver.drc_runner import DrcResult
from circuit_weaver.kicad_bridge import run_kicad
from circuit_weaver.pcb_layout import import_routing_session, place_pcb
from circuit_weaver.placement_optimizer import ComponentPlacement, _cost_connectivity


def test_real_pad_cost_distinguishes_pin_orientation():
    a = ComponentPlacement("U1", 10, 10, net_pad_offsets={"SIG": [(2, 0)]})
    b = ComponentPlacement("R1", 16, 10, net_pad_offsets={"SIG": [(-2, 0)]})
    aligned = _cost_connectivity([a, b], {})
    reversed_pin = _cost_connectivity([replace(a, rotation=180), b], {})
    assert aligned < reversed_pin
    rotated = replace(a, rotation=90)
    vertical = replace(b, x=10, y=4, rotation=90)
    assert _cost_connectivity([rotated, vertical], {}) == pytest.approx(aligned)


@pytest.mark.parametrize("failure", ["drc", "worker", "changed_board", "new_project", "changed_session"])
def test_failed_import_preserves_complete_previous_output(tmp_path, monkeypatch, failure):
    source, session, destination = (tmp_path / n for n in ("source.kicad_pcb", "input.ses", "out.kicad_pcb"))
    source.write_bytes(b"source")
    session.write_bytes(b"session")
    project = source.with_suffix(".kicad_pro")
    if failure != "new_project":
        project.write_bytes(b"source settings")
    destination.write_bytes(b"previous board")
    destination.with_suffix(".kicad_pro").write_bytes(b"previous settings")

    def worker(operation, **kwargs):
        if failure == "worker":
            return {"status": "error", "message": "failed import"}
        Path(kwargs["output"]).write_bytes(b"staged board")
        if failure == "changed_board":
            source.write_bytes(b"new source")
        if failure == "changed_session":
            session.write_bytes(b"new session")
        if failure == "new_project":
            project.write_bytes(b"concurrent project")
        return {"status": "ok"}

    monkeypatch.setattr("circuit_weaver.pcb_layout.run_kicad", worker)
    monkeypatch.setattr("circuit_weaver.pcb_layout.run_drc", lambda *a, **k: DrcResult(
        status="error" if failure == "drc" else "ok", board=str(a[0]), failure_reason="failed DRC",
    ))
    result = import_routing_session(source, session, destination, overwrite=True)
    assert result["status"] == "error"
    assert destination.read_bytes() == b"previous board"
    assert destination.with_suffix(".kicad_pro").read_bytes() == b"previous settings"
    assert not list(tmp_path.glob(".cw-import-*"))


def test_import_rejects_board_changed_since_routing_started(tmp_path, monkeypatch):
    source = tmp_path / "board.kicad_pcb"
    source.write_bytes(b"new board")
    def unexpected(*args, **kwargs):
        pytest.fail("Stale input reached KiCad")
    monkeypatch.setattr("circuit_weaver.pcb_layout.run_kicad", unexpected)
    result = import_routing_session(source, tmp_path / "input.ses", tmp_path / "out.kicad_pcb",
                                    expected_hashes={source: hashlib.sha256(b"old board").hexdigest()})
    assert result["status"] == "error"
    assert "changed" in result["message"]


def test_original_board_is_never_replaced(tmp_path):
    source = tmp_path / "board.kicad_pcb"
    source.write_bytes(b"original")
    assert place_pcb(source, source, overwrite=True)["status"] == "error"
    assert import_routing_session(source, tmp_path / "input.ses", source, overwrite=True)["status"] == "error"
    assert source.read_bytes() == b"original"


@pytest.mark.parametrize("stdout", ['CW_KICAD_RESULT=[]', 'CW_KICAD_RESULT={"status":"invalid"}', 'unexpected stdout'])
def test_worker_malformed_output_is_a_structured_error(tmp_path, monkeypatch, stdout):
    from types import SimpleNamespace

    monkeypatch.setattr("circuit_weaver.kicad_bridge.find_kicad_python", lambda *a: "python")
    monkeypatch.setattr("circuit_weaver.kicad_bridge.subprocess.run", lambda *a, **k: SimpleNamespace(
        returncode=0, stdout=stdout, stderr=""))
    board = tmp_path / "example.kicad_pcb"
    board.write_bytes(b"board")
    assert run_kicad("inspect", board=str(board))["status"] == "error"


def test_native_worker_cannot_modify_original_project(tmp_path, monkeypatch):
    import json
    from types import SimpleNamespace

    board = tmp_path / "input.kicad_pcb"
    project = board.with_suffix(".kicad_pro")
    board.write_bytes(b"board")
    project.write_bytes(b"settings")
    monkeypatch.setattr("circuit_weaver.kicad_bridge.find_kicad_python", lambda *a: "python")
    def worker(*args, **kwargs):
        request = json.loads(kwargs["input"])
        copy = Path(request["board"])
        assert copy != board
        copy.write_bytes(b"mutated by native library")
        copy.with_suffix(".kicad_pro").write_bytes(b"updated UI paths")
        return SimpleNamespace(returncode=0, stdout='CW_KICAD_RESULT={"status":"ok"}', stderr="")
    monkeypatch.setattr("circuit_weaver.kicad_bridge.subprocess.run", worker)
    assert run_kicad("inspect", board=str(board))["status"] == "ok"
    assert board.read_bytes() == b"board"
    assert project.read_bytes() == b"settings"
