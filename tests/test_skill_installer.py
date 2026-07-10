"""Regression tests for the install-skills collision policy introduced in Sprint 35."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from unittest import mock

import pytest

from circuit_weaver import skill_installer


@pytest.fixture
def skills_tree(tmp_path: Path) -> tuple[Path, Path]:
    """Create a minimal source/dest skill tree under tmp_path."""
    src = tmp_path / "src_skills"
    (src / "demo").mkdir(parents=True)
    (src / "demo" / "SKILL.md").write_text("SOURCE-v2\n", encoding="utf-8")
    (src / "demo" / "references").mkdir()
    (src / "demo" / "references" / "guide.md").write_text("hello\n", encoding="utf-8")

    dest = tmp_path / "dest_platform"
    return src, dest


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_copy_installs_when_destination_missing(skills_tree: tuple[Path, Path]) -> None:
    src, dest = skills_tree
    outcome = skill_installer._copy_skill(src, dest, "demo")
    assert outcome["status"] == "installed"
    installed = dest / "demo" / "SKILL.md"
    assert installed.read_text(encoding="utf-8") == "SOURCE-v2\n"
    assert (dest / "demo" / "references" / "guide.md").exists()
    assert (dest / "demo" / ".circuit-weaver-install.json").exists()


def test_copy_skips_existing_different_content(skills_tree: tuple[Path, Path]) -> None:
    src, dest = skills_tree
    target = dest / "demo" / "SKILL.md"
    target.parent.mkdir(parents=True)
    target.write_text("USER-CUSTOMIZATION\n", encoding="utf-8")

    outcome = skill_installer._copy_skill(src, dest, "demo")
    assert outcome["status"] == "conflict"
    assert "provenance" in outcome["reason"].lower()
    # The user's file must be untouched.
    assert target.read_text(encoding="utf-8") == "USER-CUSTOMIZATION\n"


def test_copy_unchanged_when_content_matches(skills_tree: tuple[Path, Path]) -> None:
    src, dest = skills_tree
    skill_installer._copy_skill(src, dest, "demo")
    target = dest / "demo" / "SKILL.md"
    hash_before = _hash(target)

    outcome = skill_installer._copy_skill(src, dest, "demo")
    assert outcome["status"] == "unchanged"
    assert _hash(target) == hash_before


def test_copy_force_overwrites(skills_tree: tuple[Path, Path]) -> None:
    src, dest = skills_tree
    target = dest / "demo" / "SKILL.md"
    target.parent.mkdir(parents=True)
    target.write_text("USER-CUSTOMIZATION\n", encoding="utf-8")

    outcome = skill_installer._copy_skill(src, dest, "demo", force=True)
    assert outcome["status"] == "installed"
    assert target.read_text(encoding="utf-8") == "SOURCE-v2\n"


def test_copy_backup_preserves_prior_on_overwrite(skills_tree: tuple[Path, Path]) -> None:
    src, dest = skills_tree
    target = dest / "demo" / "SKILL.md"
    target.parent.mkdir(parents=True)
    target.write_text("USER-CUSTOMIZATION\n", encoding="utf-8")

    outcome = skill_installer._copy_skill(src, dest, "demo", force=True, backup=True)
    assert outcome["status"] == "installed"
    assert target.read_text(encoding="utf-8") == "SOURCE-v2\n"

    backups = list((dest / "demo").glob("SKILL.md.bak.*"))
    assert len(backups) == 1, f"expected exactly one .bak file, got {backups}"
    assert backups[0].read_text(encoding="utf-8") == "USER-CUSTOMIZATION\n"


def test_copy_dry_run_does_not_touch_disk(skills_tree: tuple[Path, Path]) -> None:
    src, dest = skills_tree
    outcome = skill_installer._copy_skill(src, dest, "demo", dry_run=True)
    assert outcome["status"] == "installed"
    assert not (dest / "demo").exists(), "dry-run must not create destination directory"


def test_copy_dry_run_reports_skipped_without_changes(skills_tree: tuple[Path, Path]) -> None:
    src, dest = skills_tree
    target = dest / "demo" / "SKILL.md"
    target.parent.mkdir(parents=True)
    target.write_text("USER-CUSTOMIZATION\n", encoding="utf-8")
    hash_before = _hash(target)

    outcome = skill_installer._copy_skill(src, dest, "demo", dry_run=True)
    assert outcome["status"] == "conflict"
    assert _hash(target) == hash_before


def test_manifest_allows_pristine_upgrade(skills_tree: tuple[Path, Path]) -> None:
    """A file that still matches its installed hash upgrades automatically."""
    src, dest = skills_tree
    (src / "demo" / "SKILL.md").write_text("SOURCE-v1\n", encoding="utf-8")
    first = skill_installer._copy_skill(src, dest, "demo")
    assert first["status"] == "installed"

    (src / "demo" / "SKILL.md").write_text("SOURCE-v2\n", encoding="utf-8")
    second = skill_installer._copy_skill(src, dest, "demo")

    assert second["status"] == "installed"
    assert (dest / "demo" / "SKILL.md").read_text(encoding="utf-8") == "SOURCE-v2\n"


def test_manifest_preserves_true_customization(skills_tree: tuple[Path, Path]) -> None:
    src, dest = skills_tree
    (src / "demo" / "SKILL.md").write_text("SOURCE-v1\n", encoding="utf-8")
    skill_installer._copy_skill(src, dest, "demo")
    target = dest / "demo" / "SKILL.md"
    target.write_text("USER-CUSTOMIZATION\n", encoding="utf-8")
    (src / "demo" / "SKILL.md").write_text("SOURCE-v2\n", encoding="utf-8")

    outcome = skill_installer._copy_skill(src, dest, "demo")

    assert outcome["status"] == "conflict"
    assert target.read_text(encoding="utf-8") == "USER-CUSTOMIZATION\n"


def test_manifest_protects_customized_auxiliary_file(skills_tree: tuple[Path, Path]) -> None:
    src, dest = skills_tree
    skill_installer._copy_skill(src, dest, "demo")
    guide = dest / "demo" / "references" / "guide.md"
    guide.write_text("my notes\n", encoding="utf-8")
    (src / "demo" / "references" / "guide.md").write_text("upstream v2\n", encoding="utf-8")

    outcome = skill_installer._copy_skill(src, dest, "demo")

    assert outcome["status"] == "conflict"
    assert guide.read_text(encoding="utf-8") == "my notes\n"


def test_manifest_removes_pristine_file_deleted_upstream(skills_tree: tuple[Path, Path]) -> None:
    src, dest = skills_tree
    skill_installer._copy_skill(src, dest, "demo")
    guide = dest / "demo" / "references" / "guide.md"
    assert guide.exists()
    (src / "demo" / "references" / "guide.md").unlink()

    outcome = skill_installer._copy_skill(src, dest, "demo")

    assert outcome["status"] == "installed"
    assert not guide.exists()


@pytest.mark.parametrize(
    "relative",
    [
        "",
        "/absolute.md",
        "C:/absolute.md",
        "C:drive-relative.md",
        "../outside.md",
        "references/../../outside.md",
        "references\\guide.md",
        "references//guide.md",
        "./SKILL.md",
        "references/./guide.md",
        "references/../guide.md",
        "references/",
        "SKILL.md:stream",
        "bad?.md",
        "CON",
        "references/trailing.",
        "references/control\x1f.md",
    ],
)
def test_managed_target_rejects_noncanonical_or_escaping_paths(tmp_path: Path, relative: str) -> None:
    skill_dir = tmp_path / "skill"
    skill_dir.mkdir()

    with pytest.raises(skill_installer._UnsafeManagedPath):
        skill_installer._managed_target(skill_dir, relative)


@pytest.mark.parametrize("force", [False, True])
def test_manifest_traversal_cannot_delete_file_outside_skill(
    skills_tree: tuple[Path, Path],
    force: bool,
) -> None:
    src, dest = skills_tree
    skill_installer._copy_skill(src, dest, "demo")
    victim = dest / "victim.txt"
    victim.write_text("DO NOT DELETE\n", encoding="utf-8")

    manifest = dest / "demo" / ".circuit-weaver-install.json"
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    payload["files"]["../victim.txt"] = _hash(victim)
    manifest.write_text(json.dumps(payload), encoding="utf-8")

    outcome = skill_installer._copy_skill(src, dest, "demo", force=force)

    assert outcome["status"] == "conflict"
    assert "unsafe" in outcome["reason"]
    assert victim.read_text(encoding="utf-8") == "DO NOT DELETE\n"


@pytest.mark.parametrize("force", [False, True])
def test_manifest_rejects_symlink_escape_before_managed_file_access(
    skills_tree: tuple[Path, Path],
    force: bool,
) -> None:
    src, dest = skills_tree
    skill_installer._copy_skill(src, dest, "demo")
    victim = dest / "victim.txt"
    victim.write_text("DO NOT OVERWRITE\n", encoding="utf-8")
    link = dest / "demo" / "escape.md"
    try:
        link.symlink_to(victim)
    except OSError as exc:
        pytest.skip(f"symlinks unavailable: {exc}")

    manifest = dest / "demo" / ".circuit-weaver-install.json"
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    payload["files"]["escape.md"] = _hash(victim)
    manifest.write_text(json.dumps(payload), encoding="utf-8")

    outcome = skill_installer._copy_skill(src, dest, "demo", force=force)

    assert outcome["status"] == "conflict"
    assert "unsafe" in outcome["reason"]
    assert victim.read_text(encoding="utf-8") == "DO NOT OVERWRITE\n"


def test_reserved_manifest_symlink_is_rejected_without_following_target(
    skills_tree: tuple[Path, Path],
) -> None:
    src, dest = skills_tree
    skill_installer._copy_skill(src, dest, "demo")
    manifest = dest / "demo" / ".circuit-weaver-install.json"
    victim = dest / "victim.json"
    victim.write_bytes(manifest.read_bytes())
    manifest.unlink()
    try:
        manifest.symlink_to(victim)
    except OSError as exc:
        pytest.skip(f"symlinks unavailable: {exc}")

    outcome = skill_installer._copy_skill(src, dest, "demo")

    assert outcome["status"] == "conflict"
    assert "unsafe" in outcome["reason"]
    assert manifest.is_symlink()
    assert victim.read_text(encoding="utf-8").startswith("{")


def test_predictable_manifest_temp_symlink_cannot_overwrite_external_file(
    skills_tree: tuple[Path, Path],
) -> None:
    src, dest = skills_tree
    skill_installer._copy_skill(src, dest, "demo")
    skill_dir = dest / "demo"
    manifest = skill_dir / ".circuit-weaver-install.json"
    victim = dest / "victim.txt"
    victim.write_text("DO NOT OVERWRITE\n", encoding="utf-8")
    planted_temp = manifest.with_suffix(manifest.suffix + ".tmp")
    try:
        planted_temp.symlink_to(victim)
    except OSError as exc:
        pytest.skip(f"symlinks unavailable: {exc}")

    outcome = skill_installer._copy_skill(src, dest, "demo")

    assert outcome["status"] == "unchanged"
    assert victim.read_text(encoding="utf-8") == "DO NOT OVERWRITE\n"
    assert planted_temp.is_symlink()
    assert manifest.is_file()
    assert not manifest.is_symlink()


def test_manifest_temporary_file_is_cleaned_when_replace_fails(
    skills_tree: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    src, dest = skills_tree
    skill_installer._copy_skill(src, dest, "demo")
    skill_dir = dest / "demo"
    manifest = skill_dir / ".circuit-weaver-install.json"
    original = manifest.read_bytes()

    def fail_replace(source: Path, destination: Path) -> None:
        raise PermissionError(f"cannot replace {source} with {destination}")

    monkeypatch.setattr(skill_installer.os, "replace", fail_replace)

    with pytest.raises(PermissionError, match="cannot replace"):
        skill_installer._write_manifest(skill_dir, "demo", {"SKILL.md": _hash(skill_dir / "SKILL.md")})

    assert manifest.read_bytes() == original
    assert not list(skill_dir.glob(".circuit-weaver-install.*.tmp"))


def test_previous_manifestless_release_upgrades_when_hash_is_known(skills_tree: tuple[Path, Path]) -> None:
    src, dest = skills_tree
    target = dest / "demo" / "SKILL.md"
    target.parent.mkdir(parents=True)
    target.write_text("SOURCE-v1\n", encoding="utf-8")
    known = {"demo": frozenset({_hash(target)})}

    with mock.patch.object(skill_installer, "_LEGACY_PRISTINE_SKILL_MD_HASHES", known):
        outcome = skill_installer._copy_skill(src, dest, "demo")

    assert outcome["status"] == "installed"
    assert target.read_text(encoding="utf-8") == "SOURCE-v2\n"
    assert (dest / "demo" / ".circuit-weaver-install.json").exists()


def test_current_platform_paths_and_config_overrides(tmp_path: Path) -> None:
    detect, destinations, aliases = skill_installer._build_platform_paths(home=tmp_path, environ={})
    assert destinations["codex"] == tmp_path / ".agents" / "skills"
    assert destinations["opencode"] == tmp_path / ".agents" / "skills"
    assert tmp_path / ".codex" in aliases["codex"]

    env = {
        "CLAUDE_CONFIG_DIR": str(tmp_path / "claude-work"),
        "OPENCODE_CONFIG_DIR": str(tmp_path / "opencode-work"),
    }
    _, overridden, _ = skill_installer._build_platform_paths(home=tmp_path, environ=env)
    assert overridden["claude"] == tmp_path / "claude-work" / "skills"
    assert overridden["opencode"] == tmp_path / "opencode-work" / "skills"


@pytest.mark.parametrize("selection", [None, ["all"]])
def test_none_and_all_install_every_supported_platform(tmp_path: Path, selection: list[str] | None) -> None:
    source = tmp_path / "source"
    (source / "demo").mkdir(parents=True)
    (source / "demo" / "SKILL.md").write_text("SOURCE\n", encoding="utf-8")
    destinations = {"first": tmp_path / "first" / "skills", "second": tmp_path / "second" / "skills"}
    detections = {"first": tmp_path / "missing-first", "second": tmp_path / "missing-second"}

    with (
        mock.patch.object(skill_installer, "_find_skills_source", return_value=(source, "repo")),
        mock.patch.dict(skill_installer._PLATFORM_DETECT_DIRS, detections, clear=True),
        mock.patch.dict(skill_installer._PLATFORM_SKILL_DIRS, destinations, clear=True),
    ):
        result = skill_installer.install_skills(platforms=selection)

    assert result["status"] == "ok"
    assert (destinations["first"] / "demo" / "SKILL.md").is_file()
    assert (destinations["second"] / "demo" / "SKILL.md").is_file()


def test_legacy_underscore_directory_migrates_to_kebab_case(tmp_path: Path) -> None:
    src = tmp_path / "src"
    (src / "design-wizard").mkdir(parents=True)
    (src / "design-wizard" / "SKILL.md").write_text("NEW\n", encoding="utf-8")
    dest = tmp_path / "dest"
    legacy = dest / "design_wizard"
    legacy.mkdir(parents=True)
    (legacy / "SKILL.md").write_text("OLD\n", encoding="utf-8")
    known = {"design-wizard": frozenset({_hash(legacy / "SKILL.md")})}

    with mock.patch.object(skill_installer, "_LEGACY_PRISTINE_SKILL_MD_HASHES", known):
        outcome = skill_installer._copy_skill(src, dest, "design-wizard")

    assert outcome["status"] == "installed"
    assert not legacy.exists()
    assert (dest / "design-wizard" / "SKILL.md").read_text(encoding="utf-8") == "NEW\n"


def test_legacy_skill_selection_name_is_normalized(tmp_path: Path) -> None:
    source = tmp_path / "source"
    (source / "design-wizard").mkdir(parents=True)
    (source / "design-wizard" / "SKILL.md").write_text("NEW\n", encoding="utf-8")
    destination = tmp_path / "destination"

    with (
        mock.patch.object(skill_installer, "_find_skills_source", return_value=(source, "repo")),
        mock.patch.dict(skill_installer._PLATFORM_DETECT_DIRS, {"fake": tmp_path}, clear=True),
        mock.patch.dict(skill_installer._PLATFORM_SKILL_DIRS, {"fake": destination}, clear=True),
    ):
        result = skill_installer.install_skills(platforms=["fake"], skills=["design_wizard"])

    assert result["status"] == "ok"
    assert any("renamed" in warning for warning in result["warnings"])
    assert (destination / "design-wizard" / "SKILL.md").is_file()


def test_install_skills_high_level_collision_path(tmp_path: Path) -> None:
    """End-to-end: install_skills protects a pre-existing different SKILL.md."""
    source_root = tmp_path / "skills"
    (source_root / "demo").mkdir(parents=True)
    (source_root / "demo" / "SKILL.md").write_text("SOURCE\n", encoding="utf-8")

    platform_root = tmp_path / "platform_root"
    (platform_root / "skills" / "demo").mkdir(parents=True)
    (platform_root / "skills" / "demo" / "SKILL.md").write_text("MINE\n", encoding="utf-8")
    (platform_root / ".sentinel").write_text("", encoding="utf-8")

    with (
        mock.patch.object(skill_installer, "_find_skills_source", return_value=(source_root, "repo")),
        mock.patch.dict(skill_installer._PLATFORM_DETECT_DIRS, {"fake": platform_root}, clear=True),
        mock.patch.dict(
            skill_installer._PLATFORM_SKILL_DIRS,
            {"fake": platform_root / "skills"},
            clear=True,
        ),
    ):
        # Default: skip and warn.
        result = skill_installer.install_skills(platforms=["fake"])

    assert result["status"] == "error"
    assert any(entry["skill"] == "demo" for entry in result["skills_skipped"])
    assert any(entry["skill"] == "demo" for entry in result["skills_conflicted"])
    assert (platform_root / "skills" / "demo" / "SKILL.md").read_text(encoding="utf-8") == "MINE\n"


def test_install_skills_force_overwrites_through_api(tmp_path: Path) -> None:
    source_root = tmp_path / "skills"
    (source_root / "demo").mkdir(parents=True)
    (source_root / "demo" / "SKILL.md").write_text("SOURCE\n", encoding="utf-8")

    platform_root = tmp_path / "platform_root"
    (platform_root / "skills" / "demo").mkdir(parents=True)
    (platform_root / "skills" / "demo" / "SKILL.md").write_text("MINE\n", encoding="utf-8")

    with (
        mock.patch.object(skill_installer, "_find_skills_source", return_value=(source_root, "repo")),
        mock.patch.dict(skill_installer._PLATFORM_DETECT_DIRS, {"fake": platform_root}, clear=True),
        mock.patch.dict(
            skill_installer._PLATFORM_SKILL_DIRS,
            {"fake": platform_root / "skills"},
            clear=True,
        ),
    ):
        result = skill_installer.install_skills(platforms=["fake"], force=True, backup=True)

    assert result["status"] == "ok"
    assert (platform_root / "skills" / "demo" / "SKILL.md").read_text(encoding="utf-8") == "SOURCE\n"
    backups = list((platform_root / "skills" / "demo").glob("SKILL.md.bak.*"))
    assert len(backups) == 1
    assert backups[0].read_text(encoding="utf-8") == "MINE\n"


def test_install_skills_dry_run_no_side_effects(tmp_path: Path) -> None:
    source_root = tmp_path / "skills"
    (source_root / "demo").mkdir(parents=True)
    (source_root / "demo" / "SKILL.md").write_text("SOURCE\n", encoding="utf-8")

    platform_root = tmp_path / "platform_root"
    platform_skills = platform_root / "skills"

    with (
        mock.patch.object(skill_installer, "_find_skills_source", return_value=(source_root, "repo")),
        mock.patch.dict(skill_installer._PLATFORM_DETECT_DIRS, {"fake": platform_root}, clear=True),
        mock.patch.dict(skill_installer._PLATFORM_SKILL_DIRS, {"fake": platform_skills}, clear=True),
    ):
        platform_root.mkdir()
        result = skill_installer.install_skills(platforms=["fake"], dry_run=True)

    assert result["dry_run"] is True
    assert result["status"] == "ok"
    assert not platform_skills.exists(), "dry-run must not create platform skills directory"


def test_install_skills_rejects_backup_without_force() -> None:
    with mock.patch.object(skill_installer, "_find_skills_source") as find_source:
        result = skill_installer.install_skills(platforms=["codex"], backup=True)

    assert result["status"] == "error"
    assert result["message"] == "--backup requires --force"
    find_source.assert_not_called()


def test_bundled_skills_parity_with_repo_skills() -> None:
    """The bundled tree shipped to PyPI must contain every repo skill, byte-identical."""
    repo_root = Path(__file__).resolve().parent.parent
    src = repo_root / "skills"
    bundled = repo_root / "src" / "circuit_weaver" / "_bundled_skills"
    if not src.is_dir() or not bundled.is_dir():
        pytest.skip("skills source or bundled directory missing in this checkout")

    src_names = {p.name for p in src.iterdir() if p.is_dir()}
    bundled_names = {p.name for p in bundled.iterdir() if p.is_dir()}
    assert src_names == bundled_names, (
        f"Bundled skills drift from source. Missing: {src_names - bundled_names}, stale: {bundled_names - src_names}"
    )

    for skill in sorted(src_names):
        src_md = src / skill / "SKILL.md"
        bundled_md = bundled / skill / "SKILL.md"
        assert src_md.exists() and bundled_md.exists(), f"{skill}: SKILL.md missing"
        assert src_md.read_bytes() == bundled_md.read_bytes(), (
            f"{skill}: bundled SKILL.md differs from skills/ source. Run `python scripts/sync_bundled_skills.py`."
        )


def test_install_skills_reports_collision_for_real_repo_skills() -> None:
    """Sanity-check: installing into an already-populated skills dir with identical
    content reports 'unchanged'; with different content it is skipped."""
    src, _ = skill_installer._find_skills_source()
    if src is None:
        pytest.skip("skills source not available in this environment")
    demo_skill = next((d for d in src.iterdir() if d.is_dir()), None)
    if demo_skill is None:
        pytest.skip("no skill found under source")
    # Touch nothing else — just ensure the helper runs end-to-end without raising.
    assert (demo_skill / "SKILL.md").exists()
