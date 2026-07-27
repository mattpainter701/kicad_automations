from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from scripts.cleanup_branches import cleanup_branches


def _git(repo: Path, *args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=repo, text=True).strip()


def _commit(repo: Path, name: str, content: str) -> None:
    (repo / name).write_text(content)
    _git(repo, "add", name)
    _git(repo, "commit", "-m", f"add {name}")


@pytest.mark.skip_category("optional-tool")
@pytest.mark.skipif(shutil.which("git") is None, reason="git executable is required")
def test_cleanup_archives_and_deletes_only_merged_unprotected_branches(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test User")
    _commit(repo, "base.txt", "base")

    _git(repo, "checkout", "-b", "old-feature")
    _commit(repo, "old.txt", "old")
    old_sha = _git(repo, "rev-parse", "HEAD")
    _git(repo, "checkout", "main")
    _git(repo, "merge", "--no-ff", "old-feature", "-m", "merge old feature")

    _git(repo, "checkout", "-b", "new-feature")
    _commit(repo, "new.txt", "new")
    _git(repo, "checkout", "main")

    candidates = cleanup_branches(
        repo,
        base="main",
        delete=True,
        archive=True,
        force_unmerged=False,
        protected={"main"},
    )

    assert [branch.name for branch in candidates] == ["old-feature"]
    assert "old-feature" not in _git(repo, "branch", "--format=%(refname:short)").splitlines()
    assert "new-feature" in _git(repo, "branch", "--format=%(refname:short)").splitlines()
    assert _git(repo, "rev-parse", "refs/archive/branches/old-feature") == old_sha
