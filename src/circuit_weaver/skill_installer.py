"""Install Circuit Weaver skills to detected AI platforms (Claude Code, Codex, OpenCode, Kilo)."""

from __future__ import annotations

import shutil
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


def _copy_skill(src_dir: Path, dest_platform_dir: Path, skill_name: str) -> bool:
    """
    Copy a skill from source to destination platform directory.

    Copies:
    - SKILL.md (required)
    - scripts/ subdirectory (if present)
    - references/ subdirectory (if present)

    Args:
        src_dir: Source skills directory (repo/skills or _bundled_skills)
        dest_platform_dir: Destination platform skills directory
        skill_name: Name of skill to copy (e.g., "circuit-weaver", "bom")

    Returns:
        True if copy successful, False otherwise
    """
    src_skill = src_dir / skill_name
    if not src_skill.is_dir():
        return False

    dest_skill = dest_platform_dir / skill_name
    dest_skill.mkdir(parents=True, exist_ok=True)

    # Copy SKILL.md
    skill_md = src_skill / "SKILL.md"
    if skill_md.exists():
        shutil.copy2(skill_md, dest_skill / "SKILL.md")
    else:
        return False

    # Copy scripts/ if present
    src_scripts = src_skill / "scripts"
    if src_scripts.is_dir():
        dest_scripts = dest_skill / "scripts"
        shutil.copytree(src_scripts, dest_scripts, dirs_exist_ok=True)

    # Copy references/ if present
    src_references = src_skill / "references"
    if src_references.is_dir():
        dest_references = dest_skill / "references"
        shutil.copytree(src_references, dest_references, dirs_exist_ok=True)

    return True


def install_skills(platforms: list[str] | None = None, skills: list[str] | None = None) -> dict[str, Any]:
    """
    Install skills to detected or specified platforms.

    Args:
        platforms: List of platform names to install to (e.g., ["claude", "codex"]).
                   If None, auto-detects available platforms.
        skills: List of skill names to install (e.g., ["circuit-weaver", "bom"]).
                If None, installs all available skills.

    Returns:
        {
            "status": "ok" | "partial" | "error",
            "platforms_detected": [...],
            "platforms_installed": [...],
            "source": "repo" | "bundled" | "none",
            "warnings": [...],
            "message": "..."
        }
    """
    result: dict[str, Any] = {
        "status": "ok",
        "platforms_detected": [],
        "platforms_installed": [],
        "source": "none",
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
    for platform in platforms:
        if platform not in _PLATFORM_SKILL_DIRS:
            continue

        platform_skill_dir = _PLATFORM_SKILL_DIRS[platform]
        platform_skill_dir.mkdir(parents=True, exist_ok=True)

        installed_count = 0
        failed_skills = []

        for skill_name in skills_to_install:
            if _copy_skill(skills_source, platform_skill_dir, skill_name):
                installed_count += 1
            else:
                failed_skills.append(skill_name)
                partial_failure = True

        result["platforms_installed"].append(
            {
                "platform": platform,
                "skills_installed": [s for s in skills_to_install if s not in failed_skills],
                "path": str(platform_skill_dir),
            }
        )

        if failed_skills:
            result["warnings"].append(f"{platform}: failed to install {', '.join(failed_skills)}")

    # Determine final status
    if partial_failure:
        result["status"] = "partial"
        result["message"] = (
            f"Installed {sum(p.get('skills_installed', []) for p in result['platforms_installed'])} skills to {len(platforms)} platforms (with failures)"
        )
    else:
        result["status"] = "ok"
        result["message"] = f"Installed {len(skills_to_install)} skills to {len(platforms)} platform(s)"

    return result
