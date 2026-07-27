"""FastAPI web API for the schematic engine.

Exposes the BOM-to-schematic engine over HTTP for SaaS / integration use.

Endpoints:
    POST /generate             — YAML project spec -> ZIP of .kicad_sch files + report
    POST /generate/from-bom    — CSV BOM upload -> ZIP of schematics
    GET  /templates            — available subcircuit template list
    GET  /capabilities         — capability maturity and verification contract
    POST /validate             — YAML project spec -> validation results JSON
    POST /mvp/validate         — canonical/legacy design spec -> strict grouped validation
    POST /mvp/generate         — canonical/legacy design spec -> strict derived artifact ZIP
    POST /mvp/apply-patch      — transactional patch application + validation
    POST /mvp/diff             — semantic diff between two specs
    POST /mvp/pcb-feedback     — merge PCB feedback into canonical spec
    GET  /health               — service health check

Usage:
    uvicorn circuit_weaver.api:app
    # or:
    python -m circuit_weaver.api
"""

from __future__ import annotations

import hashlib
import io
import shutil
import tempfile
import zipfile
from pathlib import Path
from typing import Any

try:
    from fastapi import FastAPI, File, HTTPException, Query, Request, UploadFile
    from fastapi.responses import StreamingResponse

    _FASTAPI_AVAILABLE = True
except ImportError:
    _FASTAPI_AVAILABLE = False

# Engine version — use package version
try:
    from . import __version__ as _VERSION
except ImportError:
    _VERSION = "0+unknown"


def _get_version() -> str:
    """Return the package's single authoritative runtime version."""
    return _VERSION


def _parse_yaml_text(text: str) -> dict:
    """Parse YAML from a string with the required full YAML parser."""
    import yaml

    try:
        parsed = yaml.safe_load(text) or {}
    except yaml.YAMLError as exc:
        detail = f"Invalid YAML: {exc}"
        if _FASTAPI_AVAILABLE:
            raise HTTPException(status_code=400, detail=detail) from exc
        raise ValueError(detail) from exc
    if not isinstance(parsed, dict):
        detail = "Design specification must contain a top-level mapping"
        if _FASTAPI_AVAILABLE:
            raise HTTPException(status_code=400, detail=detail)
        raise ValueError(detail)
    return parsed


def _decode_utf8(body: bytes, *, detail: str) -> str:
    """Decode request bytes as UTF-8 with a consistent 400-style failure."""
    try:
        return body.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        if _FASTAPI_AVAILABLE:
            raise HTTPException(status_code=400, detail=detail)
        raise ValueError(detail) from exc


def _parse_spec_body_bytes(body_text: str, content_type: str) -> dict:
    """Parse a request body containing a design spec in YAML or JSON form."""
    if "yaml" in content_type or "text/plain" in content_type:
        spec = _parse_yaml_text(body_text)
    elif "json" in content_type:
        import json

        try:
            payload = json.loads(body_text)
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=400, detail=f"Invalid JSON: {exc}")
        if isinstance(payload, dict) and "yaml" in payload:
            spec = _parse_yaml_text(payload["yaml"])
        else:
            spec = payload
    else:
        # Try JSON first, then YAML as fallback for unspecified content types
        import json

        try:
            payload = json.loads(body_text)
            if isinstance(payload, dict) and "yaml" in payload:
                spec = _parse_yaml_text(payload["yaml"])
            else:
                spec = payload
        except (json.JSONDecodeError, ValueError):
            spec = _parse_yaml_text(body_text)
            if not spec:
                raise HTTPException(
                    status_code=400,
                    detail="Could not parse body as YAML or JSON. Use Content-Type: application/json or text/yaml.",
                )

    if not spec or not isinstance(spec, dict):
        raise HTTPException(status_code=400, detail="Empty or invalid project spec")
    return spec


def _resolve_project_from_spec(
    spec: dict,
    *,
    enrich_parts: bool = False,
) -> tuple[list[Any], dict, list[Any]]:
    """Resolve a parsed YAML spec into (components, metadata, validation_results).

    Returns the component list, metadata dict, and validation results.
    """
    from .project_spec import resolve_project_spec
    from .validator import run_validation_checks

    components, metadata = resolve_project_spec(spec, enrich_parts=enrich_parts)
    validation_results = run_validation_checks(components) if components else []
    return components, metadata, validation_results


def _generate_to_zip(
    components: list[Any],
    metadata: dict,
    validation_results: list[Any],
    *,
    validate: bool = True,
    hierarchical: bool = False,
    pcb: bool = False,
) -> io.BytesIO:
    """Generate schematics into a temporary directory and return a ZIP buffer."""
    from .generator import generate_from_components

    project_name = metadata.get("project", "project")
    company = metadata.get("company", "")

    tmpdir = Path(tempfile.mkdtemp(prefix="schematic_engine_"))
    try:
        generated_files = generate_from_components(
            components,
            output_dir=str(tmpdir),
            project_name=project_name,
            company=company,
            validate=validate,
            hierarchical=hierarchical,
            pcb=pcb,
            stable_uuids=True,
        )

        # Build ZIP
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for fpath in generated_files:
                zf.write(fpath, Path(fpath).name)
        buf.seek(0)
        return buf
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def _validation_results_to_json(results: list[Any], *, evidence_ledger: Any = None) -> list[dict]:
    """Convert ValidationCheckResult list to JSON-serializable dicts."""
    out = []
    for r in results:
        out.append(
            {
                "code": r.code,
                "label": r.label,
                "status": r.status,
                "issues": [
                    {
                        **issue.to_dict(),
                        "evidence_ids": (
                            sorted(
                                {evidence_id for evidence_id in issue.evidence_ids if evidence_ledger.get(evidence_id)}
                                | {
                                    evidence_ledger.record(
                                        subject_ref="tool:circuit-weaver-validator",
                                        claim=(
                                            f"{r.code}:{issue.code}:{issue.level}:"
                                            f"{issue.ref or issue.mpn}:message_sha256="
                                            f"{hashlib.sha256(str(issue.message).encode('utf-8')).hexdigest()}"
                                        ),
                                        kind="tool_result",
                                        source={
                                            "doc_id": "circuit-weaver-validator",
                                            "extraction_method": r.code,
                                        },
                                        confidence="single_source",
                                        freshness="current",
                                    )
                                }
                            )
                            if evidence_ledger is not None
                            else list(issue.evidence_ids)
                        ),
                    }
                    for issue in r.issues
                ],
            }
        )
    return out


def _get_template_info() -> list[dict]:
    """Build the template info list from the subcircuit registry."""
    from .subcircuits.base import get_default_registry

    registry = get_default_registry()
    templates = []
    for type_name in registry.available_types():
        tmpl = registry.get(type_name)
        if tmpl is None:
            continue
        params = tmpl.get_param_schema() or _infer_template_params(tmpl)
        templates.append(
            {
                "type": tmpl.template_type,
                "description": tmpl.description,
                "params": params,
            }
        )
    return templates


def _infer_template_params(tmpl: Any) -> list[str]:
    """Infer a minimal parameter schema from template source.

    Explicit schema declarations on templates are preferred. This fallback
    exists for custom templates that do not define ``param_schema`` yet.
    """
    import inspect
    import re

    try:
        source = inspect.getsource(tmpl.validate_params)
        # Match params.get("key") or params.get('key')
        found = re.findall(r'params\.get\(["\'](\w+)["\']', source)
        if found:
            seen = set()
            result = []
            for p in found:
                if p not in seen:
                    seen.add(p)
                    result.append(
                        {
                            "name": p,
                            "type": "unknown",
                            "required": False,
                            "description": "Inferred from template source",
                        }
                    )
            return result
    except (TypeError, OSError):
        pass
    # Fallback — inspect generate() for common params
    try:
        source = inspect.getsource(tmpl.generate)
        found = re.findall(r'params(?:\.get\(|\[)["\'](\w+)["\']', source)
        if found:
            seen = set()
            result = []
            for p in found:
                if p not in seen:
                    seen.add(p)
                    result.append(
                        {
                            "name": p,
                            "type": "unknown",
                            "required": False,
                            "description": "Inferred from template source",
                        }
                    )
            return result
    except (TypeError, OSError):
        pass
    return []


# ================================================================
# App factory
# ================================================================


def create_app() -> Any:
    """Create and return the FastAPI application.

    Returns None if FastAPI is not installed.
    """
    if not _FASTAPI_AVAILABLE:
        return None

    app = FastAPI(
        title="Schematic Engine API",
        description="BOM-to-KiCad schematic generation service",
        version=_get_version(),
    )

    @app.get("/health")
    async def health():
        from .subcircuits.base import get_default_registry

        registry = get_default_registry()
        return {
            "status": "ok",
            "version": _get_version(),
            "templates": len(registry),
        }

    @app.get("/templates")
    async def templates():
        return _get_template_info()

    @app.get("/capabilities")
    async def capabilities():
        """Return the capability contract shared with ``doctor --json``."""
        from .capabilities import get_capability_registry

        return get_capability_registry()

    @app.post("/generate")
    async def generate(
        request: Request,
        validate: bool = Query(True),
        hierarchical: bool = Query(False),
        pcb: bool = Query(False),
        enrich_parts: bool = Query(False),
    ):
        content_type = request.headers.get("content-type", "")
        body = await request.body()
        body_text = _decode_utf8(body, detail="Request body must be valid UTF-8")
        spec = _parse_spec_body_bytes(body_text, content_type)

        try:
            components, metadata, validation_results = _resolve_project_from_spec(
                spec,
                enrich_parts=enrich_parts,
            )
        except Exception as exc:
            raise HTTPException(status_code=422, detail=f"Failed to resolve project spec: {exc}")

        if not components:
            raise HTTPException(
                status_code=422,
                detail="No components could be resolved from the spec",
            )

        try:
            buf = _generate_to_zip(
                components,
                metadata,
                validation_results,
                validate=validate,
                hierarchical=hierarchical,
                pcb=pcb,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=f"Generation failed: {exc}")
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Generation failed: {exc}")

        project_name = metadata.get("project", "project")
        return StreamingResponse(
            buf,
            media_type="application/zip",
            headers={"Content-Disposition": f'attachment; filename="{project_name}_schematics.zip"'},
        )

    @app.post("/generate/from-bom")
    async def generate_from_bom_upload(
        file: UploadFile = File(...),
        project: str = Query("project"),
        company: str = Query(""),
        validate: bool = Query(True),
        hierarchical: bool = Query(False),
        pcb: bool = Query(False),
    ):
        if not file.filename:
            raise HTTPException(status_code=400, detail="No file uploaded")

        content = await file.read()
        csv_text = _decode_utf8(content, detail="Uploaded BOM must be valid UTF-8 CSV")

        tmpdir = Path(tempfile.mkdtemp(prefix="schematic_engine_bom_"))
        try:
            # Write the CSV to a temp file for the BOM parser
            csv_path = tmpdir / "upload.csv"
            csv_path.write_text(csv_text, encoding="utf-8")

            from .generator import generate_from_bom as _gen_bom

            try:
                generated_files = _gen_bom(
                    str(csv_path),
                    output_dir=str(tmpdir),
                    project_name=project,
                    company=company,
                    validate=validate,
                    pcb=pcb,
                    hierarchical=hierarchical,
                    stable_uuids=True,
                )
            except Exception as exc:
                raise HTTPException(status_code=422, detail=f"BOM generation failed: {exc}")

            if not generated_files:
                raise HTTPException(
                    status_code=422,
                    detail="No schematics generated — BOM may have no recognized components",
                )

            # Build ZIP
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
                for fpath in generated_files:
                    p = Path(fpath)
                    if p.exists():
                        zf.write(fpath, p.name)
                # Include any report if generated
                report_path = tmpdir / "design_report.md"
                if report_path.exists():
                    zf.write(str(report_path), report_path.name)
            buf.seek(0)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

        return StreamingResponse(
            buf,
            media_type="application/zip",
            headers={"Content-Disposition": f'attachment; filename="{project}_schematics.zip"'},
        )

    @app.post("/validate")
    async def validate_spec(request: Request, enrich_parts: bool = Query(False)):
        content_type = request.headers.get("content-type", "")
        body = await request.body()
        body_text = _decode_utf8(body, detail="Request body must be valid UTF-8")
        spec = _parse_spec_body_bytes(body_text, content_type)

        try:
            components, metadata, validation_results = _resolve_project_from_spec(
                spec,
                enrich_parts=enrich_parts,
            )
        except Exception as exc:
            raise HTTPException(status_code=422, detail=f"Failed to resolve project spec: {exc}")

        from . import __version__
        from .evidence import EvidenceLedger, collect_component_evidence

        evidence_ledger = EvidenceLedger()
        evidence_by_ref = collect_component_evidence(evidence_ledger, components)
        validation_payload = _validation_results_to_json(
            validation_results,
            evidence_ledger=evidence_ledger,
        )
        tool_id = evidence_ledger.record(
            subject_ref="tool:circuit-weaver",
            claim=f"Circuit Weaver version is {__version__}",
            kind="tool_result",
            source={"doc_id": "circuit-weaver", "extraction_method": "package-version"},
            confidence="verified",
            freshness="current",
        )
        evidence_manifest = evidence_ledger.to_manifest()

        return {
            "project": metadata.get("project", "project"),
            "component_count": len(components),
            "validation": validation_payload,
            "evidence_ids": sorted(
                {tool_id}
                | {value for values in evidence_by_ref.values() for value in values}
                | {
                    evidence_id
                    for result in validation_payload
                    for issue in result["issues"]
                    for evidence_id in issue["evidence_ids"]
                }
            ),
            "evidence_manifest": evidence_manifest,
        }

    @app.post("/mvp/validate")
    async def mvp_validate_spec(
        request: Request,
        profile: str = Query("standard"),
        enrich_parts: bool = Query(False),
    ):
        from .dispatcher import validate_design

        content_type = request.headers.get("content-type", "")
        body = await request.body()
        body_text = _decode_utf8(body, detail="Request body must be valid UTF-8")
        spec = _parse_spec_body_bytes(body_text, content_type)
        try:
            report = validate_design(spec, profile=profile, enrich_parts=enrich_parts)
        except Exception as exc:
            raise HTTPException(status_code=422, detail=f"MVP validation failed: {exc}")
        return report.to_dict()

    @app.post("/mvp/apply-patch")
    async def mvp_apply_patch(
        request: Request,
        profile: str = Query("standard"),
        enrich_parts: bool = Query(False),
    ):
        import json

        from .dispatcher import apply_design_patch

        body = await request.body()
        body_text = _decode_utf8(body, detail="Request body must be valid UTF-8")
        try:
            payload = json.loads(body_text)
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=400, detail=f"Invalid JSON: {exc}")
        spec = payload.get("spec")
        patch = payload.get("patch")
        if not isinstance(spec, dict) or not isinstance(patch, dict):
            raise HTTPException(status_code=400, detail="Payload must include object fields 'spec' and 'patch'")
        try:
            result = apply_design_patch(spec, patch, profile=profile, enrich_parts=enrich_parts)
        except Exception as exc:
            raise HTTPException(status_code=422, detail=f"Failed to apply design patch: {exc}")
        return result

    @app.post("/mvp/diff")
    async def mvp_diff(request: Request):
        import json

        from .dispatcher import diff_designs

        body = await request.body()
        body_text = _decode_utf8(body, detail="Request body must be valid UTF-8")
        try:
            payload = json.loads(body_text)
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=400, detail=f"Invalid JSON: {exc}")
        old_spec = payload.get("old_spec")
        new_spec = payload.get("new_spec")
        if not isinstance(old_spec, dict) or not isinstance(new_spec, dict):
            raise HTTPException(
                status_code=400,
                detail="Payload must include object fields 'old_spec' and 'new_spec'",
            )
        try:
            return diff_designs(old_spec, new_spec)
        except Exception as exc:
            raise HTTPException(status_code=422, detail=f"Failed to diff specs: {exc}")

    @app.post("/mvp/pcb-feedback")
    async def mvp_pcb_feedback(request: Request):
        import json

        from .dispatcher import ingest_pcb_feedback

        body = await request.body()
        body_text = _decode_utf8(body, detail="Request body must be valid UTF-8")
        try:
            payload = json.loads(body_text)
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=400, detail=f"Invalid JSON: {exc}")
        spec = payload.get("spec")
        feedback = payload.get("feedback")
        if not isinstance(spec, dict) or not isinstance(feedback, dict):
            raise HTTPException(
                status_code=400,
                detail="Payload must include object fields 'spec' and 'feedback'",
            )
        try:
            return ingest_pcb_feedback(spec, feedback).to_dict()
        except Exception as exc:
            raise HTTPException(status_code=422, detail=f"Failed to ingest PCB feedback: {exc}")

    @app.post("/mvp/generate")
    async def mvp_generate(
        request: Request,
        profile: str = Query("standard"),
        require_valid: bool = Query(True),
        enrich_parts: bool = Query(False),
        export_svg: bool = Query(True),
        require_kicad: bool = Query(False),
    ):
        from .dispatcher import generate_artifacts

        content_type = request.headers.get("content-type", "")
        body = await request.body()
        body_text = _decode_utf8(body, detail="Request body must be valid UTF-8")
        spec = _parse_spec_body_bytes(body_text, content_type)

        tmpdir = Path(tempfile.mkdtemp(prefix="schematic_engine_mvp_"))
        try:
            try:
                result = generate_artifacts(
                    spec,
                    output_dir=str(tmpdir),
                    profile=profile,
                    require_valid=require_valid,
                    enrich_parts=enrich_parts,
                    export_svg=export_svg,
                    require_kicad=require_kicad,
                )
            except Exception as exc:
                raise HTTPException(status_code=422, detail=f"MVP artifact generation failed: {exc}")

            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
                archive_files: list[tuple[str, Path]] = []
                for value in result.get("files", []):
                    path = Path(value)
                    try:
                        relative = path.resolve().relative_to(tmpdir.resolve()).as_posix()
                    except ValueError as exc:
                        raise HTTPException(
                            status_code=500,
                            detail=f"Generated artifact escaped the output directory: {path}",
                        ) from exc
                    if not path.is_file():
                        raise HTTPException(status_code=500, detail=f"Generated artifact is missing: {path}")
                    archive_files.append((relative, path))
                for relative, path in sorted(archive_files):
                    zf.write(path, relative)
            buf.seek(0)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

        project_name = result.get("project", "project")
        return StreamingResponse(
            buf,
            media_type="application/zip",
            headers={"Content-Disposition": f'attachment; filename="{project_name}_mvp_artifacts.zip"'},
        )

    return app


# Module-level app instance for `uvicorn circuit_weaver.api:app`
app = create_app()


if __name__ == "__main__":
    if not _FASTAPI_AVAILABLE:
        print("ERROR: FastAPI is not installed. Install with: pip install fastapi uvicorn")
        raise SystemExit(1)

    try:
        import uvicorn
    except ImportError:
        print("ERROR: uvicorn is not installed. Install with: pip install uvicorn")
        raise SystemExit(1)

    uvicorn.run(
        "circuit_weaver.api:app",
        host="127.0.0.1",
        port=8000,
        reload=True,
    )
