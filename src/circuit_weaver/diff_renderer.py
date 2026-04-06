"""Visual design diff — compare two YAML specs structurally and optionally as SVGs.

Usage:
    circuit-weaver diff old.yaml new.yaml --svg -o diff.html
    circuit-weaver diff old.yaml new.yaml -o diff.html       # text-only fallback
    circuit-weaver diff old.yaml new.yaml                     # stdout JSON summary
"""

from __future__ import annotations

import html
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class BlockDiff:
    """Diff record for a single design block."""

    ref: str
    block_type: str
    status: str  # "added", "removed", "changed", "unchanged"
    old_params: dict[str, Any] = field(default_factory=dict)
    new_params: dict[str, Any] = field(default_factory=dict)
    changed_fields: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "ref": self.ref,
            "type": self.block_type,
            "status": self.status,
        }
        if self.changed_fields:
            d["changed_fields"] = self.changed_fields
        if self.status == "added":
            d["params"] = self.new_params
        elif self.status == "removed":
            d["params"] = self.old_params
        elif self.status == "changed":
            d["old"] = {k: self.old_params.get(k) for k in self.changed_fields}
            d["new"] = {k: self.new_params.get(k) for k in self.changed_fields}
        return d


@dataclass
class DesignDiff:
    """Full diff between two design specs."""

    old_project: str
    new_project: str
    blocks: list[BlockDiff]
    metadata_changes: dict[str, tuple[Any, Any]] = field(default_factory=dict)

    @property
    def added(self) -> list[BlockDiff]:
        return [b for b in self.blocks if b.status == "added"]

    @property
    def removed(self) -> list[BlockDiff]:
        return [b for b in self.blocks if b.status == "removed"]

    @property
    def changed(self) -> list[BlockDiff]:
        return [b for b in self.blocks if b.status == "changed"]

    @property
    def unchanged(self) -> list[BlockDiff]:
        return [b for b in self.blocks if b.status == "unchanged"]

    def to_dict(self) -> dict[str, Any]:
        return {
            "old_project": self.old_project,
            "new_project": self.new_project,
            "summary": {
                "added": len(self.added),
                "removed": len(self.removed),
                "changed": len(self.changed),
                "unchanged": len(self.unchanged),
            },
            "metadata_changes": {k: {"old": v[0], "new": v[1]} for k, v in self.metadata_changes.items()},
            "blocks": [b.to_dict() for b in self.blocks if b.status != "unchanged"],
        }


def _extract_blocks(spec: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Extract blocks keyed by ref from a design spec.

    Returns {ref: {type, ic, ...params}} for every block in the spec.
    """
    blocks: dict[str, dict[str, Any]] = {}

    for category in ("power", "digital", "sensors", "connectors", "interfaces", "drivers", "analog"):
        items = spec.get(category, [])
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            ref = item.get("ref", f"_{category}_{len(blocks)}")
            entry = dict(item)
            entry.setdefault("_category", category)
            blocks[ref] = entry

    return blocks


def _extract_metadata(spec: dict[str, Any]) -> dict[str, Any]:
    """Extract top-level metadata fields."""
    keys = ("project", "company", "description", "version")
    return {k: spec.get(k, "") for k in keys}


def compute_diff(old_spec: dict[str, Any], new_spec: dict[str, Any]) -> DesignDiff:
    """Compute structural diff between two design specs."""
    old_blocks = _extract_blocks(old_spec)
    new_blocks = _extract_blocks(new_spec)
    old_meta = _extract_metadata(old_spec)
    new_meta = _extract_metadata(new_spec)

    all_refs = sorted(set(old_blocks) | set(new_blocks))
    diffs: list[BlockDiff] = []

    for ref in all_refs:
        old_b = old_blocks.get(ref)
        new_b = new_blocks.get(ref)

        if old_b is None and new_b is not None:
            diffs.append(
                BlockDiff(
                    ref=ref,
                    block_type=new_b.get("type", "unknown"),
                    status="added",
                    new_params=new_b,
                )
            )
        elif old_b is not None and new_b is None:
            diffs.append(
                BlockDiff(
                    ref=ref,
                    block_type=old_b.get("type", "unknown"),
                    status="removed",
                    old_params=old_b,
                )
            )
        else:
            # Both exist — check for changes
            assert old_b is not None and new_b is not None
            changed_fields = []
            all_keys = sorted(set(old_b) | set(new_b))
            for k in all_keys:
                if k.startswith("_"):
                    continue
                if old_b.get(k) != new_b.get(k):
                    changed_fields.append(k)

            status = "changed" if changed_fields else "unchanged"
            diffs.append(
                BlockDiff(
                    ref=ref,
                    block_type=new_b.get("type", old_b.get("type", "unknown")),
                    status=status,
                    old_params=old_b,
                    new_params=new_b,
                    changed_fields=changed_fields,
                )
            )

    # Metadata changes
    meta_changes = {}
    for k in sorted(set(old_meta) | set(new_meta)):
        if old_meta.get(k) != new_meta.get(k):
            meta_changes[k] = (old_meta.get(k), new_meta.get(k))

    return DesignDiff(
        old_project=old_meta.get("project", "old"),
        new_project=new_meta.get("project", "new"),
        blocks=diffs,
        metadata_changes=meta_changes,
    )


# ================================================================
# SVG generation helpers
# ================================================================


def _generate_svg(spec: dict[str, Any], work_dir: Path, label: str) -> Path | None:
    """Generate schematic + SVG for a spec. Returns SVG dir path or None."""
    from .generator import generate_from_components
    from .mvp import _find_root_schematic, _kicad_cli_path, compile_design_ir

    try:
        compiled = compile_design_ir(spec)
        sch_dir = work_dir / label
        sch_dir.mkdir(parents=True, exist_ok=True)

        files = generate_from_components(
            compiled.components,
            str(sch_dir),
            project_name=compiled.metadata.get("project", label),
            stable_uuids=True,
            validate=False,
            pcb=False,
            hierarchical=True,
        )

        root = _find_root_schematic(files, compiled.metadata.get("project", label))
        if root is None:
            return None

        cli = _kicad_cli_path()
        if cli is None:
            return None

        svg_dir = sch_dir / "svg"
        svg_dir.mkdir(parents=True, exist_ok=True)
        result = subprocess.run(
            [str(cli), "sch", "export", "svg", "-o", str(svg_dir), str(root)],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            return None

        return svg_dir

    except Exception:
        return None


# ================================================================
# HTML rendering
# ================================================================

_STATUS_COLORS = {
    "added": "#22c55e",  # green
    "removed": "#ef4444",  # red
    "changed": "#eab308",  # yellow
    "unchanged": "#6b7280",  # gray
}

_STATUS_BG = {
    "added": "#f0fdf4",
    "removed": "#fef2f2",
    "changed": "#fefce8",
    "unchanged": "#f9fafb",
}


def _render_block_row(b: BlockDiff) -> str:
    """Render one block diff as an HTML table row."""
    color = _STATUS_COLORS[b.status]
    bg = _STATUS_BG[b.status]
    badge = f'<span style="color:white;background:{color};padding:2px 8px;border-radius:4px;font-size:12px">{b.status.upper()}</span>'

    details = ""
    if b.status == "changed":
        parts = []
        for k in b.changed_fields:
            old_v = html.escape(str(b.old_params.get(k, "")))
            new_v = html.escape(str(b.new_params.get(k, "")))
            parts.append(
                f'<code>{html.escape(k)}</code>: <del style="color:#ef4444">{old_v}</del> &rarr; <ins style="color:#22c55e">{new_v}</ins>'
            )
        details = "<br>".join(parts)
    elif b.status == "added":
        params = ", ".join(f"{k}={v}" for k, v in b.new_params.items() if not k.startswith("_"))
        details = f'<span style="color:#6b7280">{html.escape(params[:200])}</span>'
    elif b.status == "removed":
        params = ", ".join(f"{k}={v}" for k, v in b.old_params.items() if not k.startswith("_"))
        details = f'<span style="color:#6b7280;text-decoration:line-through">{html.escape(params[:200])}</span>'

    return f"""<tr style="background:{bg}">
  <td style="padding:8px;font-family:monospace;font-weight:bold">{html.escape(b.ref)}</td>
  <td style="padding:8px">{html.escape(b.block_type)}</td>
  <td style="padding:8px;text-align:center">{badge}</td>
  <td style="padding:8px;font-size:13px">{details}</td>
</tr>"""


def render_html(
    diff: DesignDiff,
    old_svg_dir: Path | None = None,
    new_svg_dir: Path | None = None,
) -> str:
    """Render a full HTML diff report."""
    lines: list[str] = []
    lines.append("<!DOCTYPE html>")
    lines.append('<html lang="en"><head><meta charset="utf-8">')
    lines.append(f"<title>Design Diff: {html.escape(diff.old_project)} vs {html.escape(diff.new_project)}</title>")
    lines.append(
        "<style>body{font-family:system-ui,sans-serif;margin:20px;max-width:1400px;margin:auto}"
        "table{border-collapse:collapse;width:100%}"
        "th,td{border:1px solid #e5e7eb;text-align:left}"
        "th{background:#f3f4f6;padding:10px}"
        "h1,h2,h3{color:#1f2937}"
        ".summary{display:flex;gap:16px;margin:16px 0}"
        ".summary-card{padding:12px 20px;border-radius:8px;font-size:14px}"
        ".svg-container{display:flex;gap:20px;margin:20px 0}"
        ".svg-panel{flex:1;border:1px solid #e5e7eb;border-radius:8px;padding:12px;overflow:auto;max-height:800px}"
        ".svg-panel h3{margin-top:0}"
        "del{background:#fecaca;text-decoration:line-through}"
        "ins{background:#bbf7d0;text-decoration:none}"
        "</style></head><body>"
    )

    # Header
    lines.append("<h1>Design Diff</h1>")
    lines.append(
        f"<p><strong>{html.escape(diff.old_project)}</strong> &rarr; <strong>{html.escape(diff.new_project)}</strong></p>"
    )

    # Summary cards
    lines.append('<div class="summary">')
    for label, count, color in [
        ("Added", len(diff.added), "#22c55e"),
        ("Removed", len(diff.removed), "#ef4444"),
        ("Changed", len(diff.changed), "#eab308"),
        ("Unchanged", len(diff.unchanged), "#6b7280"),
    ]:
        lines.append(
            f'<div class="summary-card" style="background:{color}15;border:2px solid {color}">'
            f'<strong style="font-size:24px;color:{color}">{count}</strong><br>{label}</div>'
        )
    lines.append("</div>")

    # Metadata changes
    if diff.metadata_changes:
        lines.append("<h2>Metadata Changes</h2><table>")
        lines.append("<tr><th>Field</th><th>Old</th><th>New</th></tr>")
        for k, (old_v, new_v) in diff.metadata_changes.items():
            lines.append(
                f"<tr><td style='padding:8px'><code>{html.escape(k)}</code></td>"
                f"<td style='padding:8px'><del>{html.escape(str(old_v))}</del></td>"
                f"<td style='padding:8px'><ins>{html.escape(str(new_v))}</ins></td></tr>"
            )
        lines.append("</table>")

    # Block diff table
    active_blocks = [b for b in diff.blocks if b.status != "unchanged"]
    if active_blocks:
        lines.append("<h2>Block Changes</h2><table>")
        lines.append(
            "<tr><th style='width:100px'>Ref</th><th style='width:120px'>Type</th>"
            "<th style='width:100px;text-align:center'>Status</th><th>Details</th></tr>"
        )
        for b in active_blocks:
            lines.append(_render_block_row(b))
        lines.append("</table>")

    # Unchanged summary
    if diff.unchanged:
        refs = ", ".join(b.ref for b in diff.unchanged)
        lines.append(
            f"<p style='color:#6b7280;margin-top:16px'><strong>{len(diff.unchanged)} unchanged blocks:</strong> {html.escape(refs)}</p>"
        )

    # SVG side-by-side
    if old_svg_dir and new_svg_dir:
        old_svgs = sorted(old_svg_dir.glob("*.svg"))
        new_svgs = sorted(new_svg_dir.glob("*.svg"))

        if old_svgs or new_svgs:
            lines.append("<h2>Schematic Comparison</h2>")
            lines.append('<div class="svg-container">')

            # Old side
            lines.append('<div class="svg-panel">')
            lines.append(f"<h3 style='color:#ef4444'>Old: {html.escape(diff.old_project)}</h3>")
            for svg_path in old_svgs:
                svg_content = svg_path.read_text(encoding="utf-8")
                lines.append(svg_content)
            lines.append("</div>")

            # New side
            lines.append('<div class="svg-panel">')
            lines.append(f"<h3 style='color:#22c55e'>New: {html.escape(diff.new_project)}</h3>")
            for svg_path in new_svgs:
                svg_content = svg_path.read_text(encoding="utf-8")
                lines.append(svg_content)
            lines.append("</div>")

            lines.append("</div>")
    elif old_svg_dir is None and new_svg_dir is None:
        lines.append(
            '<p style="color:#6b7280;font-style:italic">SVG comparison not available '
            "(KiCad CLI not found or --svg not specified). "
            "Install KiCad 8+ for visual diff.</p>"
        )

    lines.append("</body></html>")
    return "\n".join(lines)


# ================================================================
# Public API
# ================================================================


def diff_designs(
    old_spec: dict[str, Any],
    new_spec: dict[str, Any],
    *,
    svg: bool = False,
    output: str | Path | None = None,
) -> dict[str, Any]:
    """Diff two design specs and optionally produce an HTML report.

    Args:
        old_spec: First (older) design spec dict
        new_spec: Second (newer) design spec dict
        svg: If True, generate SVG schematics for visual comparison
        output: Path to write HTML file. If None, returns JSON summary only.

    Returns:
        Summary dict with diff stats and block changes.
    """
    diff = compute_diff(old_spec, new_spec)

    old_svg_dir = None
    new_svg_dir = None

    if svg or output:
        work_dir = Path(tempfile.mkdtemp(prefix="cw_diff_"))

        if svg:
            old_svg_dir = _generate_svg(old_spec, work_dir, "old")
            new_svg_dir = _generate_svg(new_spec, work_dir, "new")

        if output:
            html_content = render_html(diff, old_svg_dir, new_svg_dir)
            output_path = Path(output)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(html_content, encoding="utf-8")

    result = diff.to_dict()
    if output:
        result["html_file"] = str(output)
    return result
