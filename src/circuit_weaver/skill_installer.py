"""Install Circuit Weaver skills to detected AI platforms (Claude Code, Codex, OpenCode, Kilo).

Collision policy
----------------
Many target users curate their own global skill library — e.g. ``~/.claude/skills/kicad/`` —
whose names collide with the skills shipped by this package. To avoid destroying that work,
``install_skills`` hashes existing ``SKILL.md`` files before overwriting:

* Byte-identical content → silent copy (treated as idempotent).
* Absent → install normally.
* Present and different → **skipped** by default and reported via ``skills_skipped``.
  The caller must pass ``force=True`` to overwrite, optionally with ``backup=True`` to
  preserve the prior version next to the target as ``SKILL.md.bak.<timestamp>``.

``dry_run=True`` performs every check but never touches disk.
"""

from __future__ import annotations

import hashlib
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

_PLATFORM_DETECT_DIRS = {
    "claude": Path.home() / ".claude",
    "codex": Path.home() / ".codex",
    "opencode": Path.home() / ".config" / "opencode",
    "kilo": Path.home() / ".kilo",
}

_PLATFORM_SKILL_DIRS = {
    "claude": Path.home() / ".claude" / "skills",
    "codex": Path.home() / ".codex" / "skills",
    "opencode": Path.home() / ".config" / "opencode" / "skills",
    "kilo": Path.home() / ".kilo" / "skills",
}


def detect_platforms() -> list[str]:
    """Return list of platform names where detection directory exists."""
    detected = []
    for platform, detect_dir in _PLATFORM_DETECT_DIRS.items():
        if detect_dir.exists():
            detected.append(platform)
    return detected


def _find_skills_source() -> tuple[Path | None, str]:
    """
    Find skills source directory.

    Tries two strategies:
    1. Strategy A (git clone / editable install): walk up from __file__ to repo root
    2. Strategy B (PyPI wheel): bundled skills in package

    Returns:
        (Path to skills directory, source type) or (None, "none") if not found
    """
    # Strategy A: git clone / editable install
    # Path: circuit_weaver/skill_installer.py -> circuit_weaver/ -> src/ -> <repo_root>/
    try:
        this_file = Path(__file__).resolve()
        circuit_weaver_dir = this_file.parent
        src_dir = circuit_weaver_dir.parent
        repo_root = src_dir.parent
        repo_skills = repo_root / "skills"

        if repo_skills.is_dir():
            return repo_skills, "repo"
    except Exception:
        pass

    # Strategy B: PyPI wheel (bundled skills)
    try:
        this_file = Path(__file__).resolve()
        circuit_weaver_package_dir = this_file.parent
        bundled_skills = circuit_weaver_package_dir / "_bundled_skills"

        if bundled_skills.is_dir():
            return bundled_skills, "bundled"
    except Exception:
        pass

    return None, "none"


def _file_hash(path: Path) -> str | None:
    """Return sha256 hex digest of a file, or None if unreadable."""
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def _backup_path(target: Path, *, now: datetime | None = None) -> Path:
    """Return the backup filename to use for ``target``."""
    ts = (now or datetime.now()).strftime("%Y%m%d_%H%M%S")
    return target.with_suffix(target.suffix + f".bak.{ts}")


def _copy_skill(
    src_dir: Path,
    dest_platform_dir: Path,
    skill_name: str,
    *,
    force: bool = False,
    backup: bool = False,
    dry_run: bool = False,
) -> dict[str, Any]:
    """
    Copy a skill from source to destination platform directory.

    Copies:
    - SKILL.md (required)
    - scripts/ subdirectory (if present)
    - references/ subdirectory (if present)

    Returns a dict:
        {"status": "installed" | "skipped" | "unchanged" | "missing_source",
         "reason": str | None,
         "dest": str}
    """
    src_skill = src_dir / skill_name
    dest_skill = dest_platform_dir / skill_name
    if not src_skill.is_dir():
        return {"status": "missing_source", "reason": "source directory missing", "dest": str(dest_skill)}

    src_md = src_skill / "SKILL.md"
    if not src_md.exists():
        return {"status": "missing_source", "reason": "source SKILL.md missing", "dest": str(dest_skill)}

    dest_md = dest_skill / "SKILL.md"

    # Collision check: existing SKILL.md with different content
    if dest_md.exists():
        src_hash = _file_hash(src_md)
        dest_hash = _file_hash(dest_md)
        if src_hash and dest_hash and src_hash == dest_hash:
            # Already up to date — still sync auxiliary dirs below in case they changed
            status = "unchanged"
            reason: str | None = None
        elif not force:
            return {
                "status": "skipped",
                "reason": "destination SKILL.md exists with different content; use --force to overwrite",
                "dest": str(dest_md),
            }
        else:
            status = "installed"
            reason = None
            if backup and not dry_run:
                try:
                    shutil.copy2(dest_md, _backup_path(dest_md))
                except OSError as exc:
                    return {
                        "status": "skipped",
                        "reason": f"backup failed before overwrite: {exc}",
                        "dest": str(dest_md),
                    }
    else:
        status = "installed"
        reason = None

    if dry_run:
        return {"status": status, "reason": reason, "dest": str(dest_md)}

    # Perform the actual copy
    dest_skill.mkdir(parents=True, exist_ok=True)
    if status != "unchanged":
        shutil.copy2(src_md, dest_md)

    # Always mirror auxiliary directories — they're additive.
    src_scripts = src_skill / "scripts"
    if src_scripts.is_dir():
        shutil.copytree(src_scripts, dest_skill / "scripts", dirs_exist_ok=True)

    src_references = src_skill / "references"
    if src_references.is_dir():
        shutil.copytree(src_references, dest_skill / "references", dirs_exist_ok=True)

    return {"status": status, "reason": reason, "dest": str(dest_md)}


def install_skills(
    platforms: list[str] | None = None,
    skills: list[str] | None = None,
    *,
    force: bool = False,
    backup: bool = False,
    dry_run: bool = False,
) -> dict[str, Any]:
    """
    Install skills to detected or specified platforms.

    Args:
        platforms: List of platform names to install to (e.g., ["claude", "codex"]).
                   If None, auto-detects available platforms.
        skills: List of skill names to install (e.g., ["circuit-weaver", "bom"]).
                If None, installs all available skills.
        force: Overwrite pre-existing SKILL.md files that have different content.
        backup: When overwriting (requires force=True), write a timestamped .bak copy first.
        dry_run: Walk the install plan without modifying disk.

    Returns:
        {
            "status": "ok" | "partial" | "error",
            "platforms_detected": [...],
            "platforms_installed": [...],
            "skills_skipped": [{"platform": ..., "skill": ..., "reason": ..., "dest": ...}],
            "source": "repo" | "bundled" | "none",
            "dry_run": bool,
            "warnings": [...],
            "message": "..."
        }
    """
    result: dict[str, Any] = {
        "status": "ok",
        "platforms_detected": [],
        "platforms_installed": [],
        "skills_skipped": [],
        "source": "none",
        "dry_run": dry_run,
        "warnings": [],
        "message": "",
    }

    # Find skills source
    skills_source, source_type = _find_skills_source()
    result["source"] = source_type

    if not skills_source:
        result["status"] = "error"
        result["message"] = "No skills source found (not in git clone, not in PyPI wheel)"
        return result

    # Detect available platforms
    detected = detect_platforms()
    result["platforms_detected"] = detected

    if not platforms:
        platforms = detected

    # Filter platforms that actually exist
    if "all" in platforms:
        platforms = detected
    else:
        valid_platforms = [p for p in platforms if p in _PLATFORM_SKILL_DIRS]
        invalid = [p for p in platforms if p not in _PLATFORM_SKILL_DIRS]
        if invalid:
            result["warnings"].append(f"Unknown platforms ignored: {', '.join(invalid)}")
        platforms = valid_platforms

    if not platforms:
        result["status"] = "error"
        result["message"] = f"No valid platforms selected. Detected: {', '.join(detected) if detected else 'none'}"
        return result

    # Determine which skills to install
    available_skills = [d.name for d in skills_source.iterdir() if d.is_dir()]

    if not skills:
        skills_to_install = available_skills
    else:
        invalid_skills = [s for s in skills if s not in available_skills]
        if invalid_skills:
            result["warnings"].append(f"Skills not found: {', '.join(invalid_skills)}")
        skills_to_install = [s for s in skills if s in available_skills]

    if not skills_to_install:
        result["status"] = "error"
        result["message"] = f"No valid skills to install. Available: {', '.join(available_skills)}"
        return result

    # Install to each platform
    partial_failure = False
    any_skipped = False
    for platform in platforms:
        if platform not in _PLATFORM_SKILL_DIRS:
            continue

        platform_skill_dir = _PLATFORM_SKILL_DIRS[platform]
        if not dry_run:
            platform_skill_dir.mkdir(parents=True, exist_ok=True)

        installed_skills: list[str] = []
        unchanged_skills: list[str] = []
        failed_skills: list[str] = []
        skipped_entries: list[dict[str, Any]] = []

        for skill_name in skills_to_install:
            outcome = _copy_skill(
                skills_source,
                platform_skill_dir,
                skill_name,
                force=force,
                backup=backup,
                dry_run=dry_run,
            )
            status = outcome["status"]
            if status == "installed":
                installed_skills.append(skill_name)
            elif status == "unchanged":
                unchanged_skills.append(skill_name)
            elif status == "skipped":
                any_skipped = True
                skipped_entries.append(
                    {
                        "platform": platform,
                        "skill": skill_name,
                        "reason": outcome.get("reason") or "skipped",
                        "dest": outcome.get("dest", ""),
                    }
                )
            else:  # missing_source etc.
                failed_skills.append(skill_name)
                partial_failure = True

        result["platforms_installed"].append(
            {
                "platform": platform,
                "skills_installed": installed_skills,
                "skills_unchanged": unchanged_skills,
                "path": str(platform_skill_dir),
            }
        )
        if skipped_entries:
            result["skills_skipped"].extend(skipped_entries)

        if failed_skills:
            result["warnings"].append(f"{platform}: failed to install {', '.join(failed_skills)}")

    # Determine final status
    total_installed = sum(len(p.get("skills_installed", [])) for p in result["platforms_installed"])
    total_unchanged = sum(len(p.get("skills_unchanged", [])) for p in result["platforms_installed"])

    if partial_failure:
        result["status"] = "partial"
        result["message"] = f"Installed {total_installed} skills to {len(platforms)} platforms (with failures)"
    elif any_skipped:
        result["status"] = "partial"
        result["message"] = (
            f"Installed {total_installed} skills; skipped {len(result['skills_skipped'])} existing "
            f"(use --force to overwrite, --backup to keep a copy)"
        )
    else:
        result["status"] = "ok"
        prefix = "Would install" if dry_run else "Installed"
        unchanged_note = f" ({total_unchanged} already up to date)" if total_unchanged else ""
        result["message"] = f"{prefix} {total_installed} skills to {len(platforms)} platform(s){unchanged_note}"

    return result
