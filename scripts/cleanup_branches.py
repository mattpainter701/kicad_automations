#!/usr/bin/env python3
"""Safely prune stale local Git branches.

The script is conservative by default: it only reports candidates. Use
``--delete`` to remove branches, and keep ``--archive`` enabled (the default)
to preserve each deleted branch tip under ``refs/archive/branches/<name>``.
"""

from __future__ import annotations

import argparse
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

PROTECTED_BRANCHES = {"main", "master", "develop", "dev", "trunk", "work"}
_REF_SAFE = re.compile(r"[^A-Za-z0-9._/-]+")


@dataclass(frozen=True)
class BranchInfo:
    name: str
    sha: str
    committerdate: str
    subject: str
    merged: bool
    current: bool


def _git(args: list[str], *, cwd: Path) -> str:
    return subprocess.check_output(["git", *args], cwd=cwd, text=True).strip()


def _safe_archive_name(branch: str) -> str:
    normalized = _REF_SAFE.sub("-", branch).strip("/-")
    return normalized.replace("..", ".") or "unnamed"


def list_local_branches(repo: Path, base: str) -> list[BranchInfo]:
    merged = set(_git(["branch", "--merged", base, "--format=%(refname:short)"], cwd=repo).splitlines())
    raw = _git(
        [
            "for-each-ref",
            "--format=%(refname:short)%00%(objectname)%00%(committerdate:short)%00%(subject)%00%(HEAD)",
            "refs/heads",
        ],
        cwd=repo,
    )
    branches: list[BranchInfo] = []
    for line in raw.splitlines():
        name, sha, date, subject, head = line.split("\0", 4)
        branches.append(
            BranchInfo(
                name=name,
                sha=sha,
                committerdate=date,
                subject=subject,
                merged=name in merged,
                current=head == "*",
            )
        )
    return branches


def cleanup_branches(
    repo: Path,
    *,
    base: str,
    delete: bool,
    archive: bool,
    force_unmerged: bool,
    protected: set[str],
) -> list[BranchInfo]:
    candidates = [
        branch
        for branch in list_local_branches(repo, base)
        if not branch.current and branch.name not in protected and (branch.merged or force_unmerged)
    ]

    for branch in candidates:
        if archive and delete:
            archive_ref = f"refs/archive/branches/{_safe_archive_name(branch.name)}"
            _git(["update-ref", archive_ref, branch.sha], cwd=repo)
        if delete:
            _git(["branch", "-D" if force_unmerged else "-d", branch.name], cwd=repo)
    return candidates


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo",
        type=Path,
        default=Path.cwd(),
        help="Git repository path (default: current directory)",
    )
    parser.add_argument("--base", default="HEAD", help="Base revision used for merged-branch detection")
    parser.add_argument(
        "--delete",
        action="store_true",
        help="Actually delete candidate branches; default is audit-only",
    )
    parser.add_argument(
        "--no-archive",
        dest="archive",
        action="store_false",
        help="Do not save deleted branch tips under refs/archive/branches",
    )
    parser.add_argument(
        "--force-unmerged",
        action="store_true",
        help="Include unmerged branches and delete them with git branch -D",
    )
    parser.add_argument(
        "--protect",
        action="append",
        default=[],
        metavar="BRANCH",
        help="Additional branch name to protect from cleanup; may be repeated",
    )
    parser.set_defaults(archive=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    protected = PROTECTED_BRANCHES | set(args.protect)
    candidates = cleanup_branches(
        args.repo,
        base=args.base,
        delete=args.delete,
        archive=args.archive,
        force_unmerged=args.force_unmerged,
        protected=protected,
    )
    mode = "Deleted" if args.delete else "Would delete"
    if not candidates:
        print("No stale local branches found.")
        return 0
    for branch in candidates:
        status = "merged" if branch.merged else "unmerged"
        print(f"{mode} {branch.name} ({status}, {branch.sha[:12]}, {branch.committerdate}) {branch.subject}")
    if not args.delete:
        print("Dry run only. Re-run with --delete to prune; archives are created by default when deleting.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
