"""MCP server for AI agent tool access to Circuit Weaver.

Exposes core operations (validate, generate, confidence, discover) as
MCP tools so AI agents can interact with the design pipeline without
going through the CLI.

Usage:
    # Run the server (stdio transport, for Claude Code / Codex):
    python -m circuit_weaver.mcp_server

    # Or with custom host/port:
    CIRCUIT_WEAVER_MCP_PORT=5000 python -m circuit_weaver.mcp_server

Tools:
    validate_design   — Validate a design spec against the strict profile
    generate_artifacts— Generate KiCad artifacts from a design spec
    discover_projects — Auto-detect Circuit Weaver projects in a directory
    research_component— Search for component information via DigiKey/LCSC
"""

from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path
from typing import Any

_logger = logging.getLogger(__name__)


def _create_app() -> Any:
    """Create and return the MCP server application."""
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError:
        print("MCP library not available. Install with: pip install mcp", file=sys.stderr)
        sys.exit(1)

    mcp = FastMCP("circuit-weaver", log_level="WARNING")

    @mcp.tool()
    def validate_design(spec_json: str) -> str:
        """Validate a circuit-weaver design spec.

        Args:
            spec_json: JSON string of the design spec (same structure as the YAML spec).

        Returns:
            JSON string of the validation report.
        """
        try:
            from circuit_weaver.dispatcher import validate_design as _validate

            spec = json.loads(spec_json)
            report = _validate(spec)
            return _report_to_json(report)
        except Exception as e:
            return json.dumps({"error": str(e)})

    @mcp.tool()
    def generate_artifacts(spec_json: str, output_dir: str = "") -> str:
        """Generate KiCad artifacts from a design spec.

        Args:
            spec_json: JSON string of the design spec.
            output_dir: Directory to write artifacts (empty = temp dir).

        Returns:
            JSON summary of generated artifacts.
        """
        try:
            from circuit_weaver.dispatcher import generate_artifacts as _generate

            spec = json.loads(spec_json)
            out = Path(output_dir) if output_dir else Path.cwd() / "output"
            out.mkdir(parents=True, exist_ok=True)
            result = _generate(spec, output_dir=out, export_svg=False)
            return json.dumps({
                "status": "ok",
                "project": result.get("project", ""),
                "files": [str(p) for p in Path(out).rglob("*") if p.is_file()],
                "root_schematic": result.get("root_schematic", ""),
            }, default=str)
        except Exception as e:
            return json.dumps({"error": str(e)})

    @mcp.tool()
    def discover_projects(root_dir: str = ".", depth: int = 2) -> str:
        """Auto-detect Circuit Weaver projects in a directory.

        Args:
            root_dir: Directory to scan for projects.
            depth: Maximum directory depth to search.

        Returns:
            JSON list of discovered projects.
        """
        try:
            from circuit_weaver.project_discovery import discover_projects as _discover

            results = _discover(root_dir=Path(root_dir), depth=depth)
            projects = []
            for p in results:
                projects.append({
                    "path": str(p.get("path", "")),
                    "name": p.get("name", ""),
                    "type": p.get("type", ""),
                    "status": p.get("status", ""),
                })
            return json.dumps({"projects": projects, "count": len(projects)})
        except Exception as e:
            return json.dumps({"error": str(e)})

    @mcp.tool()
    def research_component(query: str) -> str:
        """Search for component information via DigiKey/LCSC.

        Args:
            query: MPN, description, or keyword to search for.

        Returns:
            JSON result with component details (stock, price, datasheet).
        """
        try:
            from circuit_weaver.parts_lookup import PartsLookup

            lookup = PartsLookup()
            result = lookup.lookup(query)
            if not result:
                return json.dumps({"found": False, "query": query})
            return json.dumps({
                "found": True,
                "mpn": result.get("mpn", ""),
                "manufacturer": result.get("manufacturer", ""),
                "description": result.get("description", ""),
                "package": result.get("package", ""),
                "stock": result.get("stock", 0),
                "datasheet_url": result.get("datasheet_url", ""),
            })
        except Exception as e:
            return json.dumps({"error": str(e)})

    return mcp


def _report_to_json(report: Any) -> str:
    """Serialize a ValidationReport to JSON."""
    if hasattr(report, "to_dict"):
        return json.dumps(report.to_dict(), default=str)
    valid = getattr(report, "valid", None)
    if valid is not None:
        summary = getattr(report, "summary", {})
        categories = getattr(report, "categories", {})
        return json.dumps({
            "valid": valid,
            "summary": summary,
            "categories": {
                k: [
                    {
                        "code": getattr(v, "code", ""),
                        "level": getattr(v, "level", ""),
                        "subject": getattr(v, "subject", ""),
                        "message": getattr(v, "message", ""),
                    }
                    for v in vs
                ]
                for k, vs in (categories or {}).items()
            },
        }, default=str)
    return json.dumps({"valid": False, "error": "unknown report format"})


def main() -> None:
    """Run the MCP server."""
    port = int(os.environ.get("CIRCUIT_WEAVER_MCP_PORT", "0"))
    mcp = _create_app()

    if port:
        _logger.info("Starting Circuit Weaver MCP server on port %d", port)
        mcp.run(transport="sse", host="127.0.0.1", port=port)
    else:
        _logger.info("Starting Circuit Weaver MCP server (stdio)")
        mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
