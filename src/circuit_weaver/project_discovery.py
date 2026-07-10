"""Project discovery and auto-detection for circuit-weaver.

Scans directories for existing circuit projects by detecting:
- design.yaml (Circuit Weaver canonical projects)
- *.kicad_pro (KiCad native projects)
- *.kicad_sch (standalone schematics without a project file)

Used by skills and the CLI to auto-detect projects in the current
working directory before asking users for paths.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


@dataclass
class DiscoveredProject:
    """A discovered circuit project with metadata."""

    path: Path
    name: str
    has_design_yaml: bool = False
    has_kicad_sch: bool = False
    has_kicad_pcb: bool = False
    has_kicad_pro: bool = False
    has_design_log: bool = False
    last_modified: datetime | None = None
    component_count: int | None = None
    status: str = "unknown"  # new, in_progress, generated, validated
    project_type: str = "unknown"  # circuit_weaver, kicad_native, mixed

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": str(self.path),
            "name": self.name,
            "has_design_yaml": self.has_design_yaml,
            "has_kicad_sch": self.has_kicad_sch,
            "has_kicad_pcb": self.has_kicad_pcb,
            "has_kicad_pro": self.has_kicad_pro,
            "has_design_log": self.has_design_log,
            "last_modified": self.last_modified.isoformat() if self.last_modified else None,
            "component_count": self.component_count,
            "status": self.status,
            "project_type": self.project_type,
        }


def detect_project_type(project_dir: Path) -> str:
    """Classify a project directory.

    Returns:
        'circuit_weaver' if design.yaml exists,
        'kicad_native' if .kicad_pro exists without design.yaml,
        'mixed' if both exist,
        'unknown' otherwise.
    """
    has_yaml = (project_dir / "design.yaml").exists()
    has_pro = any(project_dir.glob("*.kicad_pro"))
    if has_yaml and has_pro:
        return "mixed"
    if has_yaml:
        return "circuit_weaver"
    if has_pro:
        return "kicad_native"
    if any(project_dir.glob("*.kicad_sch")):
        return "kicad_native"
    return "unknown"


def _infer_status(project_dir: Path) -> str:
    """Infer project status from filesystem state and design.log."""
    log_path = project_dir / "design.log"
    output_dir = project_dir / "output"

    # Check for generated artifacts
    has_output = output_dir.exists() and any(output_dir.glob("*.kicad_sch"))

    if log_path.exists():
        try:
            last_entry: dict = {}
            for line in log_path.read_text(encoding="utf-8").strip().splitlines():
                line = line.strip()
                if line:
                    last_entry = json.loads(line)

            # Check for validation results
            if last_entry.get("type") == "validation" and last_entry.get("passed"):
                return "validated"
        except Exception:
            pass

    if has_output:
        return "generated"

    if (project_dir / "design.yaml").exists():
        return "in_progress"

    return "new"


def _count_components(project_dir: Path) -> int | None:
    """Try to count components from design.yaml."""
    yaml_path = project_dir / "design.yaml"
    if not yaml_path.exists():
        return None
    try:
        from .project_spec import _parse_yaml

        spec = _parse_yaml(yaml_path)
        blocks = spec.get("blocks", [])
        return len(blocks) if blocks else None
    except Exception:
        return None


def _latest_mtime(project_dir: Path) -> datetime | None:
    """Get the most recent modification time of key project files."""
    times: list[float] = []
    for pattern in ("design.yaml", "design.log", "*.kicad_sch", "*.kicad_pcb"):
        for f in project_dir.glob(pattern):
            try:
                times.append(f.stat().st_mtime)
            except OSError:
                pass
    if times:
        return datetime.fromtimestamp(max(times))
    return None


def get_project_status(project_dir: Path) -> DiscoveredProject:
    """Get detailed status for a single project directory."""
    project_dir = Path(project_dir)
    return DiscoveredProject(
        path=project_dir,
        name=project_dir.name,
        has_design_yaml=(project_dir / "design.yaml").exists(),
        has_kicad_sch=bool(list(project_dir.glob("*.kicad_sch"))),
        has_kicad_pcb=bool(list(project_dir.glob("*.kicad_pcb"))),
        has_kicad_pro=bool(list(project_dir.glob("*.kicad_pro"))),
        has_design_log=(project_dir / "design.log").exists(),
        last_modified=_latest_mtime(project_dir),
        component_count=_count_components(project_dir),
        status=_infer_status(project_dir),
        project_type=detect_project_type(project_dir),
    )


def discover_projects(
    root_dir: Path | None = None,
    *,
    max_depth: int = 2,
) -> list[DiscoveredProject]:
    """Find all circuit projects in a directory tree.

    Detects projects by presence of:
    - design.yaml (Circuit Weaver canonical)
    - *.kicad_pro (KiCad native project)
    - *.kicad_sch without design.yaml (imported/manual KiCad)

    Args:
        root_dir: Root directory to search (default: cwd)
        max_depth: Maximum directory depth to search (default: 2)

    Returns:
        List of DiscoveredProject sorted by name.
    """
    if root_dir is None:
        root_dir = Path.cwd()
    root_dir = Path(root_dir)

    if not root_dir.exists():
        return []

    seen: set[Path] = set()
    projects: list[DiscoveredProject] = []

    def _scan(directory: Path, depth: int) -> None:
        if depth > max_depth:
            return
        try:
            items = sorted(directory.iterdir())
        except PermissionError:
            return

        for item in items:
            if not item.is_dir():
                continue
            if item.name.startswith(".") or item.name in ("__pycache__", "node_modules", ".git"):
                continue

            resolved = item.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)

            ptype = detect_project_type(item)
            if ptype != "unknown":
                projects.append(get_project_status(item))
            else:
                # Recurse deeper to find nested projects
                _scan(item, depth + 1)

    _scan(root_dir, 1)
    return sorted(projects, key=lambda p: p.name)


def format_project_table(projects: list[DiscoveredProject]) -> str:
    """Format discovered projects as a readable table.

    Returns a formatted string suitable for terminal or skill output.
    """
    if not projects:
        return "No circuit projects found."

    lines = [
        "  #  Project                  Type            Status       Files",
        "  -  -------                  ----            ------       -----",
    ]

    for i, p in enumerate(projects, 1):
        files = []
        if p.has_design_yaml:
            files.append("yaml")
        if p.has_kicad_sch:
            files.append("sch")
        if p.has_kicad_pcb:
            files.append("pcb")
        if p.has_kicad_pro:
            files.append("pro")
        if p.has_design_log:
            files.append("log")

        lines.append(
            f"  {i:<3}{p.name:<25}{p.project_type:<16}{p.status:<13}{', '.join(files)}"
        )

    return "\n".join(lines)
