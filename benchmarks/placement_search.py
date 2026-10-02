#!/usr/bin/env python3
"""Measure seeded placement search on the checked-in physical assembly corpus.

Run: python benchmarks/placement_search.py --output .test-tmp/placement-search.json
Center-based HPWL is an estimate, not a routed length or a fabrication gate.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from circuit_weaver.dispatcher import _load_spec_file, compile_design_ir  # noqa: E402
from circuit_weaver.placement_optimizer import PlacementConfig, optimize_placement  # noqa: E402
from circuit_weaver.placement_pipeline import build_placement_inventory  # noqa: E402

SAMPLES = ("usb_regulated_supply", "iot_sensor_node", "motor_controller")


def run(*, iterations: int = 3000, seed: int = 7) -> list[dict]:
    rows = []
    for name in SAMPLES:
        compiled = compile_design_ir(_load_spec_file(ROOT / "samples" / name / f"{name}.yaml"))
        inventory = build_placement_inventory(compiled.components)
        started = time.perf_counter()
        result = optimize_placement(
            inventory.components, config=PlacementConfig(iterations=iterations, seed=seed),
            constraints=list(compiled.ir.pcb_constraints),
        )
        quality = result["quality"]
        rows.append({
            "sample": name,
            "components": len(inventory.components),
            "reference_reconciliation": set(result["placements"]) == set(inventory.references),
            "seed": seed,
            "iterations": iterations,
            "elapsed_seconds": round(time.perf_counter() - started, 3),
            "overlaps": len(quality["overlaps"]),
            "outside_board": len(quality["outside_board"]),
            "support_body_violations": len(quality["support_body_violations"]),
            "constraint_violations": len(result["constraint_evaluation"]["violations"]),
            "routing_estimate": result["routing_estimate"],
            "search": result["search"],
        })
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--iterations", type=int, default=3000)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    rows = run(iterations=args.iterations, seed=args.seed)
    serialized = json.dumps(rows, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(serialized + "\n", encoding="utf-8")
    else:
        print(serialized)
    return int(any(
        not row["reference_reconciliation"] or any(row[key] for key in (
            "overlaps", "outside_board", "support_body_violations", "constraint_violations",
        ))
        for row in rows
    ))


if __name__ == "__main__":
    raise SystemExit(main())
