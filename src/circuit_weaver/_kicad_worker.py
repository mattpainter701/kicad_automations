"""Standalone pcbnew worker; stdlib only so it runs in KiCad's bundled Python."""

from __future__ import annotations

import json
import math
import sys


def _identity(board):
    result = {}
    for footprint in board.GetFootprints():
        ref = footprint.GetReference()
        if not ref or ref in result:
            raise ValueError("Board footprints require unique, nonempty references")
        result[ref] = sorted((pad.GetNumber(), pad.GetNetname()) for pad in footprint.Pads())
    return result


def _inspect(board, pcbnew):
    footprints = []
    for footprint in board.GetFootprints():
        position = footprint.GetPosition()
        rotation = footprint.GetOrientationDegrees()
        pads = [{"number": p.GetNumber(), "net": p.GetNetname(),
                 "x": pcbnew.ToMM(p.GetPosition().x), "y": pcbnew.ToMM(p.GetPosition().y)}
                for p in footprint.Pads()]
        footprint.SetOrientationDegrees(0)
        for row, pad in zip(pads, footprint.Pads()):
            row["local_x"] = pcbnew.ToMM(pad.GetPosition().x - position.x)
            row["local_y"] = pcbnew.ToMM(pad.GetPosition().y - position.y)
        courtyard_layer = pcbnew.B_CrtYd if footprint.GetLayer() == pcbnew.B_Cu else pcbnew.F_CrtYd
        courtyard = footprint.GetCourtyard(courtyard_layer)
        box = courtyard.BBox() if not courtyard.IsEmpty() else footprint.GetBoundingBox(False, False)
        # Enclose geometry about the footprint origin, including off-center
        # THT connectors; a width/height alone cannot describe such parts.
        width = 2 * max(abs(box.GetX() - position.x), abs(box.GetRight() - position.x))
        height = 2 * max(abs(box.GetY() - position.y), abs(box.GetBottom() - position.y))
        footprint.SetOrientationDegrees(rotation)
        footprints.append({
            "ref": footprint.GetReference(), "footprint": str(footprint.GetFPID().GetLibItemName()),
            "x": pcbnew.ToMM(position.x), "y": pcbnew.ToMM(position.y), "rotation": rotation,
            "layer": "back" if footprint.GetLayer() == pcbnew.B_Cu else "front",
            "locked": footprint.IsLocked(), "width": pcbnew.ToMM(width), "height": pcbnew.ToMM(height),
            "pads": pads,
        })
    box = board.GetBoardEdgesBoundingBox()
    edges = [d for d in board.GetDrawings() if d.GetLayer() == pcbnew.Edge_Cuts]
    rectangular = len(edges) == 1 and edges[0].GetShape() == pcbnew.SHAPE_T_RECT
    if len(edges) == 4 and all(d.GetShape() == pcbnew.SHAPE_T_SEGMENT for d in edges):
        points = [(d.GetStart().x, d.GetStart().y) for d in edges]
        points += [(d.GetEnd().x, d.GetEnd().y) for d in edges]
        unique = set(points)
        rectangular = (
            len(unique) == 4 and len({p[0] for p in unique}) == 2 and len({p[1] for p in unique}) == 2
            and all(points.count(p) == 2 for p in unique)
            and len({tuple(sorted(((d.GetStart().x, d.GetStart().y), (d.GetEnd().x, d.GetEnd().y))))
                     for d in edges}) == 4
            and all(d.GetStart().x == d.GetEnd().x or d.GetStart().y == d.GetEnd().y for d in edges)
        )
    return {"footprints": footprints, "track_count": len(list(board.GetTracks())),
            "zone_count": len(list(board.Zones())),
            "rectangular_outline": rectangular,
            "bounds": {"x": pcbnew.ToMM(box.GetX()), "y": pcbnew.ToMM(box.GetY()),
                       "width": pcbnew.ToMM(box.GetWidth()), "height": pcbnew.ToMM(box.GetHeight())}}


def execute(request):
    import pcbnew

    board = pcbnew.LoadBoard(request["board"])
    if board is None:
        raise ValueError("KiCad could not load the board")
    identity = _identity(board)
    operation = request["operation"]
    if operation == "inspect":
        return {"status": "ok", **_inspect(board, pcbnew)}
    if operation == "export_dsn":
        if not pcbnew.ExportSpecctraDSN(board, request["output"]):
            raise ValueError("KiCad Specctra export failed; check the board outline and netlist")
        return {"status": "ok", "version": pcbnew.Version()}
    if operation == "import_ses":
        placements = {f.GetReference(): (f.GetPosition().x, f.GetPosition().y, f.GetOrientationDegrees(), f.GetLayer())
                      for f in board.GetFootprints()}
        if not pcbnew.ImportSpecctraSES(board, request["session"]):
            raise ValueError("KiCad could not import the Specctra session")
        for f in board.GetFootprints():
            if placements[f.GetReference()] != (f.GetPosition().x, f.GetPosition().y,
                                                f.GetOrientationDegrees(), f.GetLayer()):
                raise ValueError(f"Session unexpectedly changed footprint {f.GetReference()}: "
                                 f"{placements[f.GetReference()]} -> "
                                 f"{(f.GetPosition().x, f.GetPosition().y, f.GetOrientationDegrees(), f.GetLayer())}")
    elif operation == "place":
        placements = request["placements"]
        if not placements or set(placements) - set(identity):
            raise ValueError("Placement references do not match the board")
        if len(list(board.GetTracks())) or len(list(board.Zones())):
            raise ValueError("Placement requires an unrouted board without copper zones")
        # Validate every change before any board mutation or save.
        for ref, p in placements.items():
            if not all(isinstance(p.get(k), (int, float)) and math.isfinite(p[k]) for k in ("x", "y", "rotation")):
                raise ValueError(f"{ref}: invalid placement coordinates")
            footprint = board.FindFootprintByReference(ref)
            current_layer = "back" if footprint.GetLayer() == pcbnew.B_Cu else "front"
            if p.get("layer", current_layer) != current_layer:
                raise ValueError("Automatic placement currently preserves each component's board side")
            if footprint.IsLocked() and (
                abs(pcbnew.ToMM(footprint.GetPosition().x) - p["x"]) > 1e-6
                or abs(pcbnew.ToMM(footprint.GetPosition().y) - p["y"]) > 1e-6
                or abs(footprint.GetOrientationDegrees() - p["rotation"]) % 360 > 1e-6
            ):
                raise ValueError(f"{ref}: refusing to move a locked footprint")
        for ref, p in placements.items():
            f = board.FindFootprintByReference(ref)
            f.SetPosition(pcbnew.VECTOR2I(round(p["x"] * 1_000_000), round(p["y"] * 1_000_000)))
            f.SetOrientationDegrees(p["rotation"])
    else:
        raise ValueError(f"Unknown KiCad operation: {operation}")
    if _identity(board) != identity:
        raise ValueError("Operation changed pad/net identity")
    if not pcbnew.SaveBoard(request["output"], board):
        raise ValueError("KiCad could not save the board")
    reloaded = pcbnew.LoadBoard(request["output"])
    if reloaded is None or _identity(reloaded) != identity:
        raise ValueError("Saved board failed pad/net identity verification")
    return {"status": "ok", "version": pcbnew.Version(), **_inspect(reloaded, pcbnew)}


if __name__ == "__main__":
    try:
        payload = execute(json.load(sys.stdin))
    except Exception as exc:
        payload = {"status": "error", "message": str(exc)}
    print("CW_KICAD_RESULT=" + json.dumps(payload))
    raise SystemExit(0 if payload["status"] == "ok" else 1)
