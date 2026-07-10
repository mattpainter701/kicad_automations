"""Non-destructive KiCad/Gerber import and analysis orchestration."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import unicodedata
import uuid
import zipfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from importlib import resources
from pathlib import Path, PurePosixPath
from typing import Any

from .project_state import (
    STATE_DIR_NAME,
    ensure_project_state,
    file_sha256,
    get_project_state_summary,
    manufacturing_artwork_kind,
    project_state_path,
    resolve_project_root,
    save_project_state,
    write_json_atomic,
)

_IGNORED_DIRS = {STATE_DIR_NAME, ".git", "__pycache__", ".pytest_cache", ".ruff_cache", "node_modules"}
_SHEET_FILE_RE = re.compile(r'\(property\s+"Sheetfile"\s+"([^"]+)"', re.IGNORECASE)
_WINDOWS_RESERVED_NAMES = {
    "aux",
    "con",
    "conin$",
    "conout$",
    "nul",
    "prn",
    *(f"com{index}" for index in range(1, 10)),
    *(f"lpt{index}" for index in range(1, 10)),
}


@dataclass(frozen=True)
class ArchiveLimits:
    max_files: int = 2000
    max_file_bytes: int = 128 * 1024 * 1024
    max_total_bytes: int = 512 * 1024 * 1024


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_member_path(name: str) -> PurePosixPath:
    normalized = name.replace("\\", "/")
    member = PurePosixPath(normalized)
    if not normalized or "\x00" in normalized:
        raise ValueError("ZIP contains an empty or invalid member name")
    if member.is_absolute() or ".." in member.parts or not member.parts:
        raise ValueError(f"Unsafe ZIP member path: {name}")
    for part in member.parts:
        # Apply a platform-neutral policy so an archive accepted on Linux
        # cannot alias or become an NTFS alternate data stream on Windows.
        if ":" in part:
            raise ValueError(f"Unsafe ZIP member drive or stream path: {name}")
        if part.endswith((".", " ")):
            raise ValueError(f"Unsafe ZIP member trailing dot/space alias: {name}")
        device_name = part.split(".", 1)[0].rstrip(" .").casefold()
        if device_name in _WINDOWS_RESERVED_NAMES:
            raise ValueError(f"Unsafe ZIP member reserved device name: {name}")
    return member


def safe_extract_zip(
    archive: str | Path,
    destination: str | Path,
    *,
    limits: ArchiveLimits | None = None,
) -> list[Path]:
    """Extract a bounded ZIP without traversal, symlinks, or silent overwrite."""

    limits = limits or ArchiveLimits()
    archive_path = Path(archive)
    destination_path = Path(destination)
    if destination_path.exists():
        raise FileExistsError(f"ZIP extraction destination already exists: {destination_path}")
    destination_path.mkdir(parents=True, exist_ok=False)
    destination_root = destination_path.resolve()
    extracted: list[Path] = []
    seen_names: set[str] = set()
    total_declared = 0
    total_written = 0

    try:
        with zipfile.ZipFile(archive_path) as bundle:
            members = bundle.infolist()
            files = [member for member in members if not member.is_dir()]
            if len(files) > limits.max_files:
                raise ValueError(f"ZIP contains {len(files)} files; limit is {limits.max_files}")

            for info in members:
                member = _safe_member_path(info.filename)
                canonical_name = unicodedata.normalize("NFC", member.as_posix()).casefold()
                if canonical_name in seen_names:
                    raise ValueError(f"ZIP contains a duplicate member path: {info.filename}")
                seen_names.add(canonical_name)

                unix_mode = (info.external_attr >> 16) & 0xFFFF
                if unix_mode and stat.S_ISLNK(unix_mode):
                    raise ValueError(f"ZIP symlinks are not supported: {info.filename}")
                if info.file_size > limits.max_file_bytes:
                    raise ValueError(
                        f"ZIP member {info.filename} is {info.file_size} bytes; limit is {limits.max_file_bytes}"
                    )
                total_declared += info.file_size
                if total_declared > limits.max_total_bytes:
                    raise ValueError(f"ZIP expanded size exceeds {limits.max_total_bytes} bytes")

                target = destination_path.joinpath(*member.parts)
                resolved = target.resolve(strict=False)
                if not resolved.is_relative_to(destination_root):
                    raise ValueError(f"Unsafe ZIP member path: {info.filename}")
                if info.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                if target.exists():
                    raise ValueError(f"ZIP member would overwrite an existing file: {info.filename}")
                target.parent.mkdir(parents=True, exist_ok=True)
                written_for_file = 0
                with bundle.open(info, "r") as source, target.open("xb") as output:
                    while chunk := source.read(1024 * 1024):
                        written_for_file += len(chunk)
                        total_written += len(chunk)
                        if written_for_file > limits.max_file_bytes or total_written > limits.max_total_bytes:
                            raise ValueError("ZIP expanded data exceeds configured extraction limits")
                        output.write(chunk)
                extracted.append(target)
    except Exception:
        shutil.rmtree(destination_path, ignore_errors=True)
        raise
    return extracted


def _relevant_files(source_root: Path) -> list[Path]:
    if source_root.is_file():
        candidates = [source_root]
    else:
        candidates = []
        for path in source_root.rglob("*"):
            try:
                relative = path.relative_to(source_root)
            except ValueError:
                continue
            if not path.is_file() or any(part in _IGNORED_DIRS for part in relative.parts):
                continue
            candidates.append(path)

    relevant: list[Path] = []
    for path in candidates:
        suffix = path.suffix.lower()
        if (
            suffix in {".kicad_pro", ".kicad_sch", ".sch", ".kicad_pcb", ".net", ".xml"}
            or manufacturing_artwork_kind(path) is not None
        ):
            relevant.append(path)
    return sorted(set(path.resolve() for path in relevant), key=lambda path: str(path).casefold())


def _schematic_roles(files: list[Path]) -> dict[Path, str]:
    schematics = [path for path in files if path.suffix.lower() in {".kicad_sch", ".sch"}]
    referenced: set[Path] = set()
    for schematic in schematics:
        if schematic.suffix.lower() != ".kicad_sch":
            continue
        try:
            text = schematic.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for match in _SHEET_FILE_RE.finditer(text):
            referenced.add((schematic.parent / match.group(1)).resolve(strict=False))

    project_stems = {path.stem.casefold() for path in files if path.suffix.lower() == ".kicad_pro"}
    roles: dict[Path, str] = {}
    roots = [path for path in schematics if path.resolve() not in referenced]
    for schematic in schematics:
        is_named_root = schematic.stem.casefold() in project_stems
        roles[schematic] = "root_schematic" if is_named_root or schematic in roots else "child_schematic"
    return roles


def _asset_kind(path: Path, schematic_roles: dict[Path, str]) -> tuple[str, str]:
    suffix = path.suffix.lower()
    if suffix == ".kicad_pro":
        return "kicad_project", "project"
    if suffix in {".kicad_sch", ".sch"}:
        return "schematic", schematic_roles.get(path, "schematic")
    if suffix == ".kicad_pcb":
        return "pcb", "board"
    artwork_kind = manufacturing_artwork_kind(path)
    if artwork_kind is not None:
        return artwork_kind, "manufacturing"
    if suffix in {".net", ".xml"}:
        return "netlist", "supplementary"
    return "file", "source"


def _record_path(path: Path, project_root: Path) -> tuple[str, bool]:
    try:
        return path.relative_to(project_root).as_posix(), False
    except ValueError:
        return str(path), True


def inventory_design(source_root: str | Path, project_root: str | Path) -> list[dict[str, Any]]:
    source = Path(source_root).resolve()
    root = Path(project_root).resolve()
    files = _relevant_files(source)
    roles = _schematic_roles(files)
    records: list[dict[str, Any]] = []
    for path in files:
        kind, role = _asset_kind(path, roles)
        display_path, external = _record_path(path, root)
        records.append(
            {
                "path": display_path,
                "external": external,
                "kind": kind,
                "role": role,
                "size": path.stat().st_size,
                "sha256": file_sha256(path),
            }
        )
    return records


def _project_kind(records: list[dict[str, Any]]) -> str:
    kinds = {record["kind"] for record in records}
    has_kicad = bool(kinds & {"kicad_project", "schematic", "pcb"})
    has_gerbers = bool(kinds & {"gerber", "drill", "gerber_job"})
    if has_kicad and has_gerbers:
        return "imported_mixed"
    if has_kicad:
        return "imported_kicad"
    if has_gerbers:
        return "imported_gerber"
    return "imported_files"


def _asset_path(record: dict[str, Any], root: Path) -> Path:
    value = Path(str(record["path"]))
    return value if record.get("external") or value.is_absolute() else root / value


def _default_project_root(source: Path) -> Path:
    if source.suffix.lower() == ".zip":
        return source.parent / source.stem
    return source if source.is_dir() else source.parent


def _relocate_inventory_records(
    records: list[dict[str, Any]],
    *,
    staging_root: Path,
    final_root: Path,
    project_root: Path,
) -> list[dict[str, Any]]:
    """Rewrite staging paths to their durable post-swap locations."""

    relocated: list[dict[str, Any]] = []
    for item in records:
        record = dict(item)
        actual = _asset_path(record, project_root).resolve(strict=False)
        relative = actual.relative_to(staging_root.resolve(strict=False))
        durable = (final_root / relative).resolve(strict=False)
        record["path"], record["external"] = _record_path(durable, project_root)
        relocated.append(record)
    return relocated


def _source_set_identity(records: list[dict[str, Any]], root: Path) -> tuple[tuple[Any, ...], ...]:
    """Return a stable identity for deciding whether an import is replacement."""

    identity: list[tuple[Any, ...]] = []
    for record in records:
        try:
            resolved = _asset_path(record, root).resolve(strict=False)
            normalized_path = os.path.normcase(str(resolved))
        except (KeyError, OSError, RuntimeError, ValueError):
            normalized_path = os.path.normcase(str(record.get("path", "")))
        identity.append(
            (
                str(record.get("kind", "")),
                str(record.get("role", "")),
                normalized_path,
                str(record.get("size", "")),
                str(record.get("sha256", "")),
            )
        )
    return tuple(sorted(identity, key=lambda item: tuple(str(value).casefold() for value in item)))


def _path_exists(path: Path) -> bool:
    return path.exists() or path.is_symlink()


def _remove_path(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink(missing_ok=True)
    elif path.exists():
        shutil.rmtree(path)


def _install_staged_tree(staging: Path, destination: Path) -> Path | None:
    """Atomically install staging, restoring the prior tree on swap failure."""

    backup: Path | None = None
    if _path_exists(destination):
        backup = destination.with_name(f".{destination.name}.{uuid.uuid4().hex}.backup")
        os.replace(destination, backup)
    try:
        os.replace(staging, destination)
    except BaseException:
        if backup is not None and _path_exists(backup):
            os.replace(backup, destination)
        raise
    return backup


def _rollback_staged_tree(destination: Path, backup: Path | None) -> None:
    _remove_path(destination)
    if backup is not None and _path_exists(backup):
        os.replace(backup, destination)


def import_design(
    source: str | Path,
    *,
    project_dir: str | Path | None = None,
    analyze: bool = False,
    force: bool = False,
    timeout: float = 300.0,
    archive_limits: ArchiveLimits | None = None,
) -> dict[str, Any]:
    """Inventory an existing design without modifying or regenerating it."""

    source_path = Path(source).expanduser().resolve()
    if not source_path.exists():
        raise FileNotFoundError(f"Import source does not exist: {source_path}")
    root = Path(project_dir).expanduser().resolve() if project_dir else _default_project_root(source_path).resolve()
    root.mkdir(parents=True, exist_ok=True)

    scan_root = source_path
    extract_root: Path | None = None
    staging_root: Path | None = None
    backup_root: Path | None = None
    archive_swap_installed = False
    archive_record: dict[str, Any] | None = None
    try:
        if source_path.is_file() and source_path.suffix.lower() == ".zip":
            extract_root = root / STATE_DIR_NAME / "imports" / source_path.stem
            staging_root = extract_root.with_name(f".{extract_root.name}.{uuid.uuid4().hex}.staging")
            safe_extract_zip(source_path, staging_root, limits=archive_limits)
            staged_records = inventory_design(staging_root, root)
            records = _relocate_inventory_records(
                staged_records,
                staging_root=staging_root,
                final_root=extract_root,
                project_root=root,
            )
            scan_root = extract_root
            archive_record = {
                "path": str(source_path),
                "external": not source_path.is_relative_to(root),
                "kind": "source_archive",
                "role": "import_source",
                "size": source_path.stat().st_size,
                "sha256": file_sha256(source_path),
            }
        else:
            if source_path.is_file():
                # A single KiCad file normally depends on sibling sheets/boards.
                scan_root = source_path.parent
            records = inventory_design(scan_root, root)

        if archive_record is not None:
            records.insert(0, archive_record)
        analyzable = [record for record in records if record["kind"] != "source_archive"]
        if not analyzable:
            raise ValueError(
                f"No supported KiCad, PCB, Gerber, drill, or netlist files found in {source_path}"
            )

        project_name = next(
            (Path(record["path"]).stem for record in records if record["kind"] == "kicad_project"),
            source_path.stem,
        )
        state = ensure_project_state(root)
        sources_differ = bool(state.sources) and (
            _source_set_identity(state.sources, root) != _source_set_identity(records, root)
        )
        if sources_differ and not force:
            raise ValueError(
                "Import source set differs from the durable project state; "
                "pass --force to replace it explicitly"
            )

        if extract_root is not None and staging_root is not None:
            existing_stage_matches = False
            if _path_exists(extract_root):
                try:
                    existing_records = inventory_design(extract_root, root)
                    existing_stage_matches = _source_set_identity(
                        existing_records, root
                    ) == _source_set_identity(analyzable, root)
                except (OSError, ValueError):
                    existing_stage_matches = False
                if not existing_stage_matches and not force:
                    raise FileExistsError(
                        f"Import staging at {extract_root} differs; pass --force to replace it"
                    )

            if existing_stage_matches:
                _remove_path(staging_root)
                staging_root = None
            else:
                backup_root = _install_staged_tree(staging_root, extract_root)
                archive_swap_installed = True
                staging_root = None

        if sources_differ:
            prior_import = state.workflow.get("import")
            if isinstance(prior_import, dict):
                history = state.workflow.get("import_history")
                import_history = list(history) if isinstance(history, list) else []
                import_history.append(dict(prior_import))
                state.workflow["import_history"] = import_history[-100:]
            state.analyses = {}
            state.artifacts = [
                artifact for artifact in state.artifacts if artifact.get("kind") != "analysis_index"
            ]

        state.name = project_name
        state.kind = _project_kind(records)
        state.sources = records
        state.status = "imported"
        state.current_phase = "imported"
        state.last_error = ""
        state.workflow["import"] = {
            "source": str(source_path),
            "scan_root": str(scan_root),
            "completed_at": _now_iso(),
            "source_count": len(records),
        }
        state.next_actions = [f'circuit-weaver analyze-design "{root}"', f'circuit-weaver status "{root}"']
        manifest_path = save_project_state(root, state)
    except BaseException:
        if archive_swap_installed and extract_root is not None:
            try:
                _rollback_staged_tree(extract_root, backup_root)
            except Exception as rollback_exc:
                raise RuntimeError(
                    f"Import failed and ZIP staging rollback also failed; prior staging is at {backup_root}"
                ) from rollback_exc
        if staging_root is not None and _path_exists(staging_root):
            _remove_path(staging_root)
        raise
    else:
        if backup_root is not None and _path_exists(backup_root):
            try:
                _remove_path(backup_root)
            except OSError:
                # The committed manifest points at the new tree. A hidden
                # rollback copy is safer than failing after the commit.
                pass

    result = {
        "status": "imported",
        "project_root": str(root),
        "manifest": str(manifest_path),
        "project_id": state.project_id,
        "kind": state.kind,
        "source_count": len(records),
        "sources": records,
        "next_actions": state.next_actions,
    }
    if analyze:
        result["analysis"] = analyze_design(root, force=force, timeout=timeout)
    return result


def _analysis_fingerprint(records: list[dict[str, Any]]) -> str:
    digest = hashlib.sha256()
    for record in sorted(records, key=lambda item: str(item.get("path", "")).casefold()):
        for value in (
            record.get("kind", ""),
            record.get("role", ""),
            record.get("path", ""),
            record.get("size", ""),
            record.get("sha256", ""),
            record.get("missing", False),
        ):
            digest.update(str(value).encode("utf-8"))
            digest.update(b"\0")
    return digest.hexdigest()


def _refresh_source_records(records: list[dict[str, Any]], root: Path) -> None:
    """Refresh source hashes immediately before constructing analysis jobs."""

    for record in records:
        if record.get("kind") == "source_archive":
            continue
        try:
            path = _asset_path(record, root)
            if not path.is_file():
                record["missing"] = True
                continue
            record["size"] = path.stat().st_size
            record["sha256"] = file_sha256(path)
            record.pop("missing", None)
        except (KeyError, OSError, ValueError):
            record["missing"] = True


def _bundled_scripts_resource() -> Any:
    return resources.files("circuit_weaver").joinpath("_bundled_skills", "kicad", "scripts")


def _bundled_resource_bytes(filename: str) -> bytes:
    resource = _bundled_scripts_resource().joinpath(filename)
    if not resource.is_file():
        raise FileNotFoundError(f"Bundled analyzer is missing: {filename}")
    return resource.read_bytes()


def _analyzer_fingerprint(script_name: str) -> str:
    """Fingerprint executable analyzer code and its shared parser dependency."""

    digest = hashlib.sha256()
    for filename in (script_name, "sexp_parser.py"):
        digest.update(filename.encode("utf-8"))
        digest.update(b"\0")
        digest.update(_bundled_resource_bytes(filename))
        digest.update(b"\0")
    return digest.hexdigest()


def _copy_resource_tree(source: Any, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    for child in source.iterdir():
        target = destination / child.name
        if child.is_dir():
            _copy_resource_tree(child, target)
        elif child.is_file():
            target.write_bytes(child.read_bytes())


@contextmanager
def _materialized_bundled_scripts() -> Iterator[Path]:
    """Yield the complete analyzer directory for filesystem subprocess use."""

    resource = _bundled_scripts_resource()
    try:
        filesystem_path = Path(os.fspath(resource))
    except TypeError:
        filesystem_path = None
    if filesystem_path is not None and filesystem_path.is_dir():
        yield filesystem_path
        return

    with tempfile.TemporaryDirectory(prefix="circuit-weaver-analyzers-") as temporary:
        scripts_path = Path(temporary) / "scripts"
        _copy_resource_tree(resource, scripts_path)
        yield scripts_path


def _json_object_sha256(path: Path) -> str:
    data = path.read_bytes()
    payload = json.loads(data.decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Analyzer JSON output must be an object")
    return hashlib.sha256(data).hexdigest()


def _cached_analysis_is_valid(
    prior: dict[str, Any],
    *,
    root: Path,
    source_fingerprint: str,
    analyzer_fingerprint: str,
) -> bool:
    if prior.get("status") != "ok":
        return False
    if prior.get("source_fingerprint") != source_fingerprint:
        return False
    if prior.get("analyzer_fingerprint") != analyzer_fingerprint:
        return False
    expected_output_hash = str(prior.get("output_sha256", ""))
    output_value = str(prior.get("output", ""))
    if not expected_output_hash or not output_value:
        return False
    output_path = Path(output_value)
    if not output_path.is_absolute():
        output_path = root / output_path
    try:
        return _json_object_sha256(output_path) == expected_output_hash
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError):
        return False


def _run_analyzer(
    script_name: str,
    input_path: Path,
    output_path: Path,
    *,
    timeout: float,
) -> dict[str, Any]:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_name(f".{output_path.name}.{uuid.uuid4().hex}.tmp")
    started = _now_iso()
    try:
        with _materialized_bundled_scripts() as scripts_path:
            script = scripts_path / script_name
            if not script.is_file():
                raise FileNotFoundError(f"Bundled analyzer is missing: {script_name}")
            script_sha256 = file_sha256(script)
            analyzer_fingerprint = _analyzer_fingerprint(script_name)
            command = [
                sys.executable,
                str(script),
                str(input_path),
                "--output",
                str(temporary),
                "--compact",
            ]
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                check=False,
                shell=False,
            )
        if completed.returncode != 0:
            raise RuntimeError(
                f"Analyzer exited {completed.returncode}: {(completed.stderr or completed.stdout).strip()[:1000]}"
            )
        if not temporary.is_file():
            raise RuntimeError("Analyzer completed without writing its JSON output")
        _json_object_sha256(temporary)
        os.replace(temporary, output_path)
        return {
            "status": "ok",
            "started_at": started,
            "completed_at": _now_iso(),
            "input": str(input_path),
            "output": str(output_path),
            "script": script_name,
            "script_sha256": script_sha256,
            "analyzer_fingerprint": analyzer_fingerprint,
            "output_sha256": _json_object_sha256(output_path),
        }
    except subprocess.TimeoutExpired as exc:
        raise TimeoutError(f"Analyzer timed out after {timeout:g} seconds: {script_name}") from exc
    finally:
        temporary.unlink(missing_ok=True)


def _safe_output_stem(path: Path) -> str:
    stem = re.sub(r"[^A-Za-z0-9_.-]+", "_", path.stem).strip("._")
    return stem or "design"


def _analysis_jobs(state_sources: list[dict[str, Any]], root: Path) -> list[dict[str, Any]]:
    schematic_records = [record for record in state_sources if record.get("kind") == "schematic"]
    roots = [record for record in schematic_records if record.get("role") == "root_schematic"]
    if not roots and schematic_records:
        roots = [schematic_records[0]]

    jobs: list[dict[str, Any]] = []
    for record in roots:
        path = _asset_path(record, root)
        jobs.append(
            {
                "key": f"schematic:{record['path']}",
                "kind": "schematic",
                "script": "analyze_schematic.py",
                "input": path,
                # The bundled analyzer follows hierarchical Sheetfile links,
                # including into subdirectories. Hash every inventoried sheet
                # so an edited child can never reuse a stale root analysis.
                "records": schematic_records,
            }
        )
    for record in [item for item in state_sources if item.get("kind") == "pcb"]:
        jobs.append(
            {
                "key": f"pcb:{record['path']}",
                "kind": "pcb",
                "script": "analyze_pcb.py",
                "input": _asset_path(record, root),
                "records": [record],
            }
        )

    gerber_records = [
        record for record in state_sources if record.get("kind") in {"gerber", "drill", "gerber_job"}
    ]
    by_directory: dict[Path, list[dict[str, Any]]] = {}
    for record in gerber_records:
        path = _asset_path(record, root)
        by_directory.setdefault(path.parent, []).append(record)
    for directory, records in sorted(by_directory.items(), key=lambda item: str(item[0]).casefold()):
        jobs.append(
            {
                "key": f"gerbers:{directory}",
                "kind": "gerbers",
                "script": "analyze_gerbers.py",
                "input": directory,
                "records": records,
            }
        )
    return jobs


def analyze_design(
    project: str | Path,
    *,
    force: bool = False,
    timeout: float = 300.0,
) -> dict[str, Any]:
    """Run every applicable bundled analyzer and persist restartable results."""

    root = resolve_project_root(project)
    state = ensure_project_state(root)
    if not state.sources:
        # Opening an unmanaged native project is equivalent to a non-destructive import.
        import_design(root, project_dir=root)
        state = ensure_project_state(root)

    _refresh_source_records(state.sources, root)
    jobs = _analysis_jobs(state.sources, root)
    analysis_dir = root / STATE_DIR_NAME / "analysis"
    analysis_dir.mkdir(parents=True, exist_ok=True)
    state.current_phase = "analysis"
    state.status = "analyzing"
    state.last_error = ""
    save_project_state(root, state)

    results: dict[str, dict[str, Any]] = {}
    for index, job in enumerate(jobs, 1):
        fingerprint = _analysis_fingerprint(job["records"])
        prior_value = state.analyses.get(job["key"], {})
        prior = prior_value if isinstance(prior_value, dict) else {}
        output = analysis_dir / f"{index:02d}_{job['kind']}_{_safe_output_stem(job['input'])}.json"
        analyzer_fingerprint = ""
        try:
            analyzer_fingerprint = _analyzer_fingerprint(job["script"])
            if not force and _cached_analysis_is_valid(
                prior,
                root=root,
                source_fingerprint=fingerprint,
                analyzer_fingerprint=analyzer_fingerprint,
            ):
                results[job["key"]] = {**prior, "cached": True}
                continue

            entry = _run_analyzer(job["script"], job["input"], output, timeout=timeout)
            if not isinstance(entry, dict):
                raise TypeError("Analyzer runner result must be an object")
            entry["output_sha256"] = _json_object_sha256(output)
            entry["analyzer_fingerprint"] = analyzer_fingerprint
            entry["source_fingerprint"] = fingerprint
            entry["kind"] = job["kind"]
            entry["cached"] = False
        except Exception as exc:
            entry = {
                "status": "error",
                "completed_at": _now_iso(),
                "input": str(job["input"]),
                "output": str(output),
                "script": job["script"],
                "source_fingerprint": fingerprint,
                "analyzer_fingerprint": analyzer_fingerprint,
                "kind": job["kind"],
                "error": str(exc),
                "cached": False,
            }
        state.analyses[job["key"]] = entry
        results[job["key"]] = entry
        save_project_state(root, state)

    if not jobs:
        state.status = "analysis_failed"
        state.current_phase = "analysis_failed"
        state.last_error = "No analyzable schematic, PCB, or Gerber inputs were found"
        state.next_actions = [f'circuit-weaver import-design "{root}" --force']
    elif all(entry.get("status") == "ok" for entry in results.values()):
        state.status = "analyzed"
        state.current_phase = "analysis_complete"
        state.next_actions = [
            f'circuit-weaver status "{root}"',
            f"Review {analysis_dir / 'index.json'}",
        ]
    else:
        state.status = "analysis_failed"
        state.current_phase = "analysis_failed"
        failures = [
            entry.get("error", "unknown analysis error")
            for entry in results.values()
            if entry.get("status") != "ok"
        ]
        state.last_error = "; ".join(failures)[:2000]
        state.next_actions = [f'circuit-weaver analyze-design "{root}" --force']

    index_payload = {
        "schema_version": 1,
        "project_id": state.project_id,
        "project_root": str(root),
        "status": state.status,
        "generated_at": _now_iso(),
        "results": results,
    }
    index_path = analysis_dir / "index.json"
    write_json_atomic(index_path, index_payload)
    artifact = {
        "path": index_path.relative_to(root).as_posix(),
        "kind": "analysis_index",
        "status": state.status,
        "sha256": file_sha256(index_path),
    }
    state.artifacts = [item for item in state.artifacts if item.get("kind") != "analysis_index"] + [artifact]
    save_project_state(root, state)

    return {
        "status": state.status,
        "project_root": str(root),
        "manifest": str(project_state_path(root)),
        "analysis_index": str(index_path),
        "results": results,
        "next_actions": state.next_actions,
        "summary": get_project_state_summary(root),
    }
