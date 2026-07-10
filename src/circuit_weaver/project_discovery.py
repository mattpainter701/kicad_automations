"""Project discovery for generated, native KiCad, and Gerber projects."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from .project_state import (
    STATE_DIR_NAME,
    get_project_state_summary,
    manufacturing_artwork_kind,
    project_state_path,
)

_IGNORED_DIRS = {STATE_DIR_NAME, ".git", "__pycache__", ".pytest_cache", ".ruff_cache", "node_modules"}


def _is_ignored(path: Path, root: Path) -> bool:
    try:
        return any(part in _IGNORED_DIRS for part in path.relative_to(root).parts)
    except ValueError:
        return True


def _project_files(project_dir: Path) -> Iterable[Path]:
    try:
        for path in project_dir.rglob("*"):
            if path.is_file() and not _is_ignored(path, project_dir):
                yield path
    except (OSError, PermissionError):
        return


def _is_gerber(path: Path) -> bool:
    return manufacturing_artwork_kind(path) is not None


@dataclass
class DiscoveredProject:
    """A discovered circuit project with enough metadata to reopen it."""

    path: Path
    name: str
    has_design_yaml: bool = False
    has_kicad_sch: bool = False
    has_kicad_pcb: bool = False
    has_kicad_pro: bool = False
    has_design_log: bool = False
    last_modified: datetime | None = None
    component_count: int | None = None
    status: str = "unknown"
    project_type: str = "unknown"
    has_gerbers: bool = False
    has_project_state: bool = False
    project_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": str(self.path),
            "name": self.name,
            "has_design_yaml": self.has_design_yaml,
            "has_kicad_sch": self.has_kicad_sch,
            "has_kicad_pcb": self.has_kicad_pcb,
            "has_kicad_pro": self.has_kicad_pro,
            "has_design_log": self.has_design_log,
            "has_gerbers": self.has_gerbers,
            "has_project_state": self.has_project_state,
            "project_id": self.project_id,
            "last_modified": self.last_modified.isoformat() if self.last_modified else None,
            "component_count": self.component_count,
            "status": self.status,
            "project_type": self.project_type,
        }


def detect_project_type(project_dir: Path) -> str:
    """Classify canonical, native KiCad, PCB-only, and Gerber projects."""

    project_dir = Path(project_dir)
    state_path = project_state_path(project_dir)
    if state_path.is_file():
        try:
            kind = str(get_project_state_summary(project_dir).get("kind", ""))
            if kind:
                return kind
        except (OSError, ValueError):
            pass

    try:
        files = [path for path in project_dir.iterdir() if path.is_file()]
    except OSError:
        files = []
    has_yaml = (project_dir / "design.yaml").is_file()
    has_pro = any(path.suffix.lower() == ".kicad_pro" for path in files)
    has_schematic = any(path.suffix.lower() in {".kicad_sch", ".sch"} for path in files)
    has_pcb = any(path.suffix.lower() == ".kicad_pcb" for path in files)
    has_gerber = any(_is_gerber(path) for path in files)
    if has_yaml and (has_pro or has_schematic or has_pcb):
        return "mixed"
    if has_yaml:
        return "circuit_weaver"
    if has_pro or has_schematic or has_pcb:
        return "kicad_native"
    if has_gerber:
        return "gerber_native"
    return "unknown"


def _infer_status(project_dir: Path) -> str:
    try:
        return str(get_project_state_summary(project_dir)["status"])
    except (OSError, ValueError):
        return "unknown"


def _count_components(project_dir: Path) -> int | None:
    yaml_path = project_dir / "design.yaml"
    if not yaml_path.exists():
        return None
    try:
        from .project_spec import _simple_yaml_parse

        spec = _simple_yaml_parse(yaml_path.read_text(encoding="utf-8"))
        blocks = spec.get("blocks", [])
        return len(blocks) if blocks else None
    except Exception:
        return None


def _latest_mtime(project_dir: Path) -> datetime | None:
    times: list[float] = []
    for path in _project_files(project_dir):
        if path.name in {"design.yaml", "design.log", "project.json"} or path.suffix.lower() in {
            ".kicad_sch",
            ".sch",
            ".kicad_pcb",
            ".kicad_pro",
        } or _is_gerber(path):
            try:
                times.append(path.stat().st_mtime)
            except OSError:
                pass
    return datetime.fromtimestamp(max(times)) if times else None


def get_project_status(project_dir: Path) -> DiscoveredProject:
    """Get detailed reconciled status for one project directory."""

    project_dir = Path(project_dir).resolve()
    files = list(_project_files(project_dir))
    summary: dict[str, Any] = {}
    try:
        summary = get_project_state_summary(project_dir)
    except (OSError, ValueError):
        pass
    inventory = dict(summary.get("inventory") or {})
    return DiscoveredProject(
        path=project_dir,
        name=str(summary.get("name") or project_dir.name),
        has_design_yaml=(project_dir / "design.yaml").is_file()
        or bool(inventory.get("design_specs")),
        has_kicad_sch=any(path.suffix.lower() in {".kicad_sch", ".sch"} for path in files)
        or bool(inventory.get("schematics")),
        has_kicad_pcb=any(path.suffix.lower() == ".kicad_pcb" for path in files)
        or bool(inventory.get("pcbs")),
        has_kicad_pro=any(path.suffix.lower() == ".kicad_pro" for path in files)
        or bool(inventory.get("kicad_projects")),
        has_design_log=(project_dir / "design.log").is_file(),
        has_gerbers=any(_is_gerber(path) for path in files)
        or bool(inventory.get("gerber_files")),
        has_project_state=project_state_path(project_dir).is_file(),
        project_id=str(summary.get("project_id", "")),
        last_modified=_latest_mtime(project_dir),
        component_count=_count_components(project_dir),
        status=str(summary.get("status") or _infer_status(project_dir)),
        project_type=detect_project_type(project_dir),
    )


def discover_projects(
    root_dir: Path | None = None,
    *,
    max_depth: int = 2,
) -> list[DiscoveredProject]:
    """Find projects, including when ``root_dir`` is itself a project."""

    root = Path.cwd() if root_dir is None else Path(root_dir)
    if not root.exists():
        return []
    root = root.resolve()

    if detect_project_type(root) != "unknown":
        return [get_project_status(root)]

    projects: list[DiscoveredProject] = []
    seen: set[Path] = set()

    def _scan(directory: Path, depth: int) -> None:
        if depth > max_depth:
            return
        try:
            items = sorted(directory.iterdir(), key=lambda item: item.name.casefold())
        except (OSError, PermissionError):
            return
        for item in items:
            if not item.is_dir() or item.name.startswith(".") or item.name in _IGNORED_DIRS:
                continue
            try:
                resolved = item.resolve()
            except OSError:
                continue
            if resolved in seen:
                continue
            seen.add(resolved)
            if detect_project_type(item) != "unknown":
                projects.append(get_project_status(item))
            else:
                _scan(item, depth + 1)

    _scan(root, 1)
    return sorted(projects, key=lambda project: project.name.casefold())


def format_project_table(projects: list[DiscoveredProject]) -> str:
    if not projects:
        return "No circuit projects found."

    lines = [
        "  #  Project                  Type            Status       Files",
        "  -  -------                  ----            ------       -----",
    ]
    for index, project in enumerate(projects, 1):
        files = []
        if project.has_design_yaml:
            files.append("yaml")
        if project.has_kicad_sch:
            files.append("sch")
        if project.has_kicad_pcb:
            files.append("pcb")
        if project.has_kicad_pro:
            files.append("pro")
        if project.has_gerbers:
            files.append("gerber")
        if project.has_design_log:
            files.append("log")
        if project.has_project_state:
            files.append("state")
        lines.append(
            f"  {index:<3}{project.name:<25}{project.project_type:<16}{project.status:<13}{', '.join(files)}"
        )
    return "\n".join(lines)
