"""Concurrency guarantees for durable project state."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from circuit_weaver.project_state import (
    ConcurrentProjectStateUpdate,
    ProjectState,
    load_project_state,
    project_state_path,
    save_project_state,
)


def test_state_revision_advances_on_each_successful_save(tmp_path: Path) -> None:
    state = ProjectState(name="RevisionBoard")

    save_project_state(tmp_path, state)
    assert state.revision == 1
    save_project_state(tmp_path, state)
    assert state.revision == 2

    persisted = load_project_state(tmp_path)
    assert persisted is not None
    assert persisted.revision == 2
    assert (tmp_path / ".circuit-weaver" / "project.lock").is_file()


def test_stale_state_snapshot_cannot_overwrite_newer_update(tmp_path: Path) -> None:
    initial = ProjectState(name="ConcurrentBoard")
    save_project_state(tmp_path, initial)
    first = load_project_state(tmp_path)
    stale = load_project_state(tmp_path)
    assert first is not None and stale is not None

    first.status = "analyzing"
    save_project_state(tmp_path, first)
    stale.status = "generated"

    with pytest.raises(ConcurrentProjectStateUpdate, match="changed from revision 1 to 2"):
        save_project_state(tmp_path, stale)

    persisted = load_project_state(tmp_path)
    assert persisted is not None
    assert persisted.status == "analyzing"
    assert persisted.revision == 2
    assert stale.revision == 1


def test_legacy_manifest_without_revision_upgrades_on_save(tmp_path: Path) -> None:
    path = project_state_path(tmp_path)
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "project_id": "legacy-id",
                "name": "Legacy",
                "status": "in_progress",
            }
        ),
        encoding="utf-8",
    )

    legacy = load_project_state(tmp_path)
    assert legacy is not None
    assert legacy.revision == 0
    save_project_state(tmp_path, legacy)

    upgraded = json.loads(path.read_text(encoding="utf-8"))
    assert upgraded["revision"] == 1


def test_new_project_identity_cannot_replace_existing_manifest(tmp_path: Path) -> None:
    save_project_state(tmp_path, ProjectState(name="Original"))

    with pytest.raises(ConcurrentProjectStateUpdate, match="different project"):
        save_project_state(tmp_path, ProjectState(name="Replacement"))
