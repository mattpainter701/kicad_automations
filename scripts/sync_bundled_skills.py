#!/usr/bin/env python3
"""Sync ``skills/`` into ``src/circuit_weaver/_bundled_skills/``.

The bundled copy is what ships inside the PyPI wheel and is what
``circuit-weaver install-skills`` uses on machines that don't have the git
clone. Without this sync, PyPI users get a stale and incomplete skill library.

Usage:
    python scripts/sync_bundled_skills.py           # rewrite the bundled tree to match skills/
    python scripts/sync_bundled_skills.py --check   # exit 1 if drift exists (for CI / pre-commit)
"""

from __future__ import annotations

import argparse
import filecmp
import shutil
import sys
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _compare_trees(src: Path, dest: Path) -> list[str]:
    """Return a list of drift descriptions between src and dest. Empty means in sync."""
    drift: list[str] = []

    if not src.exists():
        drift.append(f"missing source: {src}")
        return drift

    if not dest.exists():
        drift.append(f"missing destination: {dest}")
        return drift

    src_names = sorted(p.name for p in src.iterdir() if p.is_dir())
    dest_names = sorted(p.name for p in dest.iterdir() if p.is_dir())

    for name in src_names:
        if name not in dest_names:
            drift.append(f"skill missing from bundle: {name}")

    for name in dest_names:
        if name not in src_names:
            drift.append(f"stale skill in bundle (not in source): {name}")

    for name in src_names:
        if name not in dest_names:
            continue
        drift.extend(_dir_drift(src / name, dest / name))

    return drift


def _dir_drift(src: Path, dest: Path, prefix: str = "") -> list[str]:
    """Recursively list byte-level drift between two directory trees."""
    cmp = filecmp.dircmp(src, dest)
    drift: list[str] = []
    rel_prefix = prefix or src.name
    for name in cmp.left_only:
        drift.append(f"{rel_prefix}/{name}: missing in bundle")
    for name in cmp.right_only:
        drift.append(f"{rel_prefix}/{name}: stale in bundle")
    for name in cmp.diff_files:
        drift.append(f"{rel_prefix}/{name}: content differs")
    for name in cmp.funny_files:
        drift.append(f"{rel_prefix}/{name}: unreadable")
    for name in cmp.common_dirs:
        drift.extend(_dir_drift(src / name, dest / name, f"{rel_prefix}/{name}"))
    return drift


def sync(src: Path, dest: Path) -> None:
    """Rewrite ``dest`` to be a byte-identical copy of ``src``."""
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(src, dest)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Do not modify files. Exit 1 if drift exists between skills/ and bundled copy.",
    )
    args = parser.parse_args(argv)

    repo = _repo_root()
    src = repo / "skills"
    dest = repo / "src" / "circuit_weaver" / "_bundled_skills"

    if not src.exists():
        print(f"error: source {src} not found", file=sys.stderr)
        return 2

    drift = _compare_trees(src, dest)

    if args.check:
        if drift:
            print("Bundled skills are out of sync with skills/ — rerun sync_bundled_skills.py:", file=sys.stderr)
            for line in drift:
                print(f"  - {line}", file=sys.stderr)
            return 1
        print("Bundled skills are in sync.")
        return 0

    if not drift:
        print("Bundled skills already in sync.")
        return 0

    sync(src, dest)
    print(f"Synced {sum(1 for _ in (dest).iterdir() if _.is_dir())} skills from {src} to {dest}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
