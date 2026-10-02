"""Place and finish routing existing real KiCad boards through native pcbnew."""

from __future__ import annotations

import hashlib
import shutil
import tempfile
from pathlib import Path
from typing import Any

from .autoroute import _prepare_destination, preflight_pcb
from .component_db import ComponentDef, PinDef
from .drc_runner import run_drc
from .evidence import EvidenceLedger
from .kicad_bridge import run_kicad
from .pcb_handoff import _pcb_output_lock, _publish_staged_transaction
from .placement_optimizer import PlacementConfig, optimize_placement


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _prepare_settings(source: Path, staged: Path) -> dict[Path, str | None]:
    snapshots = {source: _hash(source)}
    for suffix in (".kicad_pro", ".kicad_dru"):
        origin = source.with_suffix(suffix)
        if origin.is_file():
            snapshots[origin] = _hash(origin)
            shutil.copy2(origin, staged.with_suffix(suffix))
        else:
            snapshots[origin] = None
    return snapshots


def _check_snapshots(snapshots: dict[Path, str | None]) -> None:
    for source, digest in snapshots.items():
        if (_hash(source) if source.exists() else None) != digest:
            raise ValueError("Source board, session, or project settings changed during processing")


def _restore_settings(source: Path, staged: Path, snapshots: dict[Path, str | None]) -> None:
    _check_snapshots(snapshots)
    for suffix in (".kicad_pro", ".kicad_dru"):
        origin, target = source.with_suffix(suffix), staged.with_suffix(suffix)
        if origin.is_file():
            shutil.copy2(origin, target)
        elif target.exists():
            # Discard defaults/UI state emitted by native SaveBoard. The
            # source had no project here; validate with the same defaults.
            target.unlink()


def _publish(staged: Path, destination: Path, snapshots: dict[Path, str | None], overwrite: bool) -> None:
    publications = [(staged, destination)]
    for suffix in (".kicad_pro", ".kicad_dru"):
        source = staged.with_suffix(suffix)
        if source.is_file():
            publications.append((source, destination.with_suffix(suffix)))
    with _pcb_output_lock(destination.parent):
        _check_snapshots(snapshots)
        for _, target in publications:
            error = _prepare_destination(target, overwrite=overwrite)
            if error:
                raise ValueError(error)
            if target == destination:
                for suffix in (".kicad_pro", ".kicad_dru"):
                    if not staged.with_suffix(suffix).exists() and target.with_suffix(suffix).exists():
                        raise ValueError("Output has unrelated project settings; choose a fresh output name")
        _publish_staged_transaction(staged.parent, publications)


def place_pcb(
    board_path: str | Path, output_path: str | Path, *, iterations: int = 5000, seed: int = 0,
    overwrite: bool = False, kicad_python_path: str | Path | None = None,
) -> dict[str, Any]:
    """Place an unrouted rectangular board, preserving all real pads and nets."""
    source, destination = Path(board_path).resolve(), Path(output_path).resolve()
    try:
        if destination.suffix.lower() != ".kicad_pcb":
            raise ValueError("Placement output must be a .kicad_pcb file")
        if source == destination:
            raise ValueError("Choose a separate output board to preserve the original PCB")
        preflight = preflight_pcb(source)
        if not preflight["routable"]:
            raise ValueError(preflight["reason"])
        error = _prepare_destination(destination, overwrite=overwrite)
        if error:
            raise ValueError(error)
        original_snapshots = {
            path: _hash(path) if path.exists() else None
            for path in (source, source.with_suffix(".kicad_pro"), source.with_suffix(".kicad_dru"))
        }
        inspection = run_kicad("inspect", board=str(source), python_path=kicad_python_path)
        if inspection["status"] != "ok":
            return inspection
        if not inspection["rectangular_outline"]:
            raise ValueError("Automatic placement currently requires a closed rectangular Edge.Cuts outline")
        if inspection["track_count"] or inspection["zone_count"]:
            raise ValueError("Automatic placement requires an unrouted board without copper zones")
        bounds = inspection["bounds"]
        constraints = []
        components = []
        for item in inspection["footprints"]:
            component = ComponentDef(
                mpn=item["ref"], source_ref=item["ref"], footprint=item["footprint"],
                category="connector" if item["ref"].startswith("J") else "other",
                pins=[PinDef(p["number"], p["number"], "passive", "L") for p in item["pads"]],
                pin_nets={p["number"]: p["net"] for p in item["pads"] if p["net"]},
            )
            component.placement_width_mm = item["width"]
            component.placement_height_mm = item["height"]
            component.placement_layer = item["layer"]
            component.placement_geometry_status = "board_geometry"
            component.placement_pad_offsets = {}
            for pad in item["pads"]:
                if pad["net"]:
                    component.placement_pad_offsets.setdefault(pad["net"], []).append((pad["local_x"], pad["local_y"]))
            components.append(component)
            if item["locked"]:
                constraints.append({"kind": "placement", "target": item["ref"],
                                    "x_mm": item["x"] - bounds["x"], "y_mm": item["y"] - bounds["y"],
                                    "rotation": item["rotation"], "layer": item["layer"]})
        result = optimize_placement(
            components, config=PlacementConfig(board_width_mm=bounds["width"], board_height_mm=bounds["height"],
                                                iterations=iterations, seed=seed), constraints=constraints,
        )
        if result["quality"]["review_required"]:
            return {"status": "error", "message": "No valid placement found within the board constraints",
                    "placement": result}
        placements = {ref: {**p, "x": p["x"] + bounds["x"], "y": p["y"] + bounds["y"]}
                      for ref, p in result["placements"].items()}
        result["placements"] = placements
        result["coordinate_origin"] = "kicad_board"
        with tempfile.TemporaryDirectory(prefix=".cw-place-", dir=destination.parent) as folder:
            staged = Path(folder) / destination.name
            snapshots = _prepare_settings(source, staged)
            snapshots.update(original_snapshots)
            applied = run_kicad("place", board=str(source), output=str(staged), placements=placements,
                                python_path=kicad_python_path)
            if applied["status"] != "ok":
                return applied
            _restore_settings(source, staged, snapshots)
            drc = run_drc(staged, evidence_ledger=EvidenceLedger())
            # An unrouted board necessarily has unconnected pads. All other
            # DRC errors still prevent publication, including pad clearances.
            blockers = [f for f in drc.findings if f.severity == "blocker" and f.rule_id != "CW-DRC-002"]
            if drc.status != "ok" or blockers:
                return {"status": "error", "message": "Placed board failed physical DRC", "drc": drc.to_dict()}
            _publish(staged, destination, snapshots, overwrite)
        return {"status": "ok", "output_path": str(destination), "output_kind": "placed_kicad_board",
                "placement": result, "drc": {**drc.to_dict(), "board": str(destination)}, "fabrication_ready": False,
                "message": "Real footprints placed and physical DRC checked; the board still requires routing"}
    except (OSError, ValueError) as exc:
        return {"status": "error", "message": str(exc)}


def import_routing_session(
    board_path: str | Path, session_path: str | Path, output_path: str | Path, *,
    overwrite: bool = False, kicad_python_path: str | Path | None = None,
    expected_hashes: dict[Path, str | None] | None = None,
) -> dict[str, Any]:
    """Import routes into a separate PCB and publish only after native KiCad DRC."""
    source, session, destination = Path(board_path).resolve(), Path(session_path).resolve(), Path(output_path).resolve()
    try:
        if destination.suffix.lower() != ".kicad_pcb":
            raise ValueError("Routed board output must be a .kicad_pcb file")
        if source == destination:
            raise ValueError("Choose a separate output board to preserve the original PCB")
        if expected_hashes:
            _check_snapshots(expected_hashes)
        error = _prepare_destination(destination, overwrite=overwrite)
        if error:
            raise ValueError(error)
        with tempfile.TemporaryDirectory(prefix=".cw-import-", dir=destination.parent) as folder:
            staged = Path(folder) / destination.name
            snapshots = _prepare_settings(source, staged)
            snapshots.update(expected_hashes or {})
            snapshots[session] = _hash(session)
            imported = run_kicad("import_ses", board=str(source), session=str(session), output=str(staged),
                                 python_path=kicad_python_path)
            if imported["status"] != "ok":
                return imported
            _restore_settings(source, staged, snapshots)
            drc = run_drc(staged, evidence_ledger=EvidenceLedger())
            if not drc.passed:
                return {"status": "error", "message": "Imported routing failed KiCad DRC; board was not published",
                        "drc": drc.to_dict()}
            _publish(staged, destination, snapshots, overwrite)
        return {"status": "ok", "output_path": str(destination), "output_kind": "routed_kicad_board",
                "drc": {**drc.to_dict(), "board": str(destination)},
                "routing_complete": True, "fabrication_ready": False}
    except (OSError, ValueError) as exc:
        return {"status": "error", "message": str(exc)}
