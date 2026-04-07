"""Interactive PCB placement viewer — generates an HTML/SVG page.

Features: click-to-highlight nets, hover for component info, thermal heatmap
overlay, DFM clearance display, and CSV placement export.

Usage:
    from circuit_weaver.placement_viewer import generate_viewer
    html = generate_viewer(components, placements, board_width=100, board_height=80)
"""

from __future__ import annotations

import html as html_mod
import json
from pathlib import Path

from .component_db import ComponentDef

# Color palette by category
_CATEGORY_COLORS: dict[str, str] = {
    "power": "#ef4444",
    "digital": "#3b82f6",
    "analog": "#8b5cf6",
    "comms": "#06b6d4",
    "connector": "#22c55e",
    "sensor": "#f59e0b",
    "passive": "#a3a3a3",
    "semiconductor": "#ec4899",
    "other": "#737373",
}

_THERMAL_GRADIENT = [
    (0.0, "#3b82f6"),  # cool blue
    (0.25, "#22d3ee"),  # cyan
    (0.5, "#facc15"),  # yellow
    (0.75, "#f97316"),  # orange
    (1.0, "#ef4444"),  # hot red
]


def _estimate_size(comp: ComponentDef) -> tuple[float, float]:
    """Estimate component size from footprint."""
    fp = (comp.footprint or "").upper()
    sizes = {
        "0201": (0.6, 0.3),
        "0402": (1.0, 0.5),
        "0603": (1.6, 0.8),
        "0805": (2.0, 1.25),
        "1206": (3.2, 1.6),
        "SOT-23": (2.9, 1.3),
        "SOT-223": (6.5, 3.5),
        "SOIC-8": (5.0, 4.0),
        "SOIC-16": (10.3, 4.0),
        "QFN-16": (3.0, 3.0),
        "QFN-24": (4.0, 4.0),
        "QFN-32": (5.0, 5.0),
        "QFN-48": (7.0, 7.0),
        "LQFP-48": (9.0, 9.0),
        "LQFP-64": (12.0, 12.0),
        "LQFP-100": (16.0, 16.0),
        "BGA": (15.0, 15.0),
        "USB-C": (9.0, 7.5),
    }
    for pattern, size in sizes.items():
        if pattern in fp:
            return size
    prefix = comp.source_ref[:1].upper() if comp.source_ref else ""
    if prefix in ("R", "C", "L"):
        return (1.6, 0.8)
    if prefix == "U":
        return (5.0, 5.0)
    if prefix == "J":
        return (8.0, 5.0)
    return (2.0, 2.0)


def _thermal_color(watts: float, max_watts: float) -> str:
    """Map power dissipation to a heatmap color."""
    if max_watts <= 0:
        return _THERMAL_GRADIENT[0][1]
    t = min(watts / max_watts, 1.0)
    for i in range(len(_THERMAL_GRADIENT) - 1):
        t0, c0 = _THERMAL_GRADIENT[i]
        t1, c1 = _THERMAL_GRADIENT[i + 1]
        if t0 <= t <= t1:
            f = (t - t0) / (t1 - t0) if t1 > t0 else 0
            r0, g0, b0 = int(c0[1:3], 16), int(c0[3:5], 16), int(c0[5:7], 16)
            r1, g1, b1 = int(c1[1:3], 16), int(c1[3:5], 16), int(c1[5:7], 16)
            r = int(r0 + (r1 - r0) * f)
            g = int(g0 + (g1 - g0) * f)
            b = int(b0 + (b1 - b0) * f)
            return f"#{r:02x}{g:02x}{b:02x}"
    return _THERMAL_GRADIENT[-1][1]


def generate_viewer(
    components: list[ComponentDef],
    placements: dict[str, dict],
    board_width_mm: float = 100.0,
    board_height_mm: float = 80.0,
    *,
    thermal_data: dict[str, dict] | None = None,
    title: str = "PCB Placement Viewer",
    output_path: str | Path | None = None,
) -> str:
    """Generate an interactive HTML placement viewer.

    Args:
        components: ComponentDef list from compiled design.
        placements: {ref: {x, y, rotation, layer}} placement dict.
        board_width_mm: Board width in mm.
        board_height_mm: Board height in mm.
        thermal_data: Optional thermal specs {mpn: {pdiss_max_w, theta_ja, ...}}.
        title: Page title.
        output_path: Write HTML to this path (optional).

    Returns:
        HTML string.
    """
    scale = 8.0  # px per mm
    svg_w = board_width_mm * scale
    svg_h = board_height_mm * scale
    pad = 40  # padding for labels

    # Build component data for JS
    comp_map: dict[str, dict] = {}
    for comp in components:
        ref = comp.source_ref or ""
        if not ref or ref not in placements:
            continue
        p = placements[ref]
        w, h = _estimate_size(comp)
        cat = (comp.category or "other").lower()
        mpn = comp.mpn or ""
        thermal = (thermal_data or {}).get(mpn, {})
        pdiss = thermal.get("pdiss_max_w", 0) if isinstance(thermal.get("pdiss_max_w"), (int, float)) else 0

        comp_map[ref] = {
            "ref": ref,
            "value": comp.value or "",
            "mpn": mpn,
            "footprint": comp.footprint or "",
            "category": cat,
            "x": p.get("x", 0),
            "y": p.get("y", 0),
            "rotation": p.get("rotation", 0),
            "layer": p.get("layer", "front"),
            "width": w,
            "height": h,
            "color": _CATEGORY_COLORS.get(cat, "#737373"),
            "pdiss_w": pdiss,
            "nets": [n for n in (comp.pin_nets or {}).values() if n],
        }

    max_pdiss = max((c["pdiss_w"] for c in comp_map.values()), default=0)

    # Build net map for highlighting
    net_components: dict[str, list[str]] = {}
    for ref, data in comp_map.items():
        for net in data["nets"]:
            if net not in net_components:
                net_components[net] = []
            net_components[net].append(ref)

    comp_json = json.dumps(comp_map, ensure_ascii=False)
    net_json = json.dumps(net_components, ensure_ascii=False)

    # Generate SVG component rects
    svg_rects = []
    for ref, c in comp_map.items():
        x = c["x"] * scale
        y = c["y"] * scale
        w = c["width"] * scale
        h = c["height"] * scale
        color = c["color"]
        label = html_mod.escape(ref)
        value = html_mod.escape(c["value"])

        svg_rects.append(
            f'<g class="comp" data-ref="{html_mod.escape(ref)}" '
            f'transform="translate({x:.1f},{y:.1f}) rotate({c["rotation"]})">'
            f'<rect x="{-w / 2:.1f}" y="{-h / 2:.1f}" width="{w:.1f}" height="{h:.1f}" '
            f'fill="{color}" fill-opacity="0.7" stroke="{color}" stroke-width="1" rx="1"/>'
            f'<text x="0" y="0" text-anchor="middle" dominant-baseline="central" '
            f'font-size="{max(7, min(w * 0.35, 11)):.0f}" fill="white" font-weight="bold">{label}</text>'
            f"</g>"
        )

    # Thermal overlay rects (hidden by default)
    thermal_rects = []
    if max_pdiss > 0:
        for ref, c in comp_map.items():
            if c["pdiss_w"] > 0:
                x = c["x"] * scale
                y = c["y"] * scale
                w = c["width"] * scale + 4
                h = c["height"] * scale + 4
                tc = _thermal_color(c["pdiss_w"], max_pdiss)
                thermal_rects.append(
                    f'<rect class="thermal-overlay" x="{x - w / 2:.1f}" y="{y - h / 2:.1f}" '
                    f'width="{w:.1f}" height="{h:.1f}" fill="{tc}" fill-opacity="0.4" '
                    f'rx="2" style="display:none" data-ref="{html_mod.escape(ref)}"/>'
                )

    svg_content = "\n".join(svg_rects)
    thermal_content = "\n".join(thermal_rects)

    # Build CSS styles (break long declarations across lines)
    css_styles = (
        "* { margin: 0; padding: 0; box-sizing: border-box; }\n"
        "body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI',"
        " sans-serif; background: #0f172a; color: #e2e8f0; }\n"
        ".container { max-width: 1400px; margin: 0 auto; padding: 16px; }\n"
        "h1 { font-size: 1.25rem; margin-bottom: 12px; color: #94a3b8; }\n"
        ".toolbar { display: flex; gap: 8px; margin-bottom: 12px; "
        "flex-wrap: wrap; align-items: center; }\n"
        ".toolbar button { padding: 6px 14px; border: 1px solid #334155; "
        "border-radius: 6px; background: #1e293b; color: #e2e8f0; "
        "cursor: pointer; font-size: 0.85rem; }\n"
        ".toolbar button:hover { background: #334155; }\n"
        ".toolbar button.active { background: #3b82f6; border-color: #3b82f6; }\n"
        ".board-container { position: relative; overflow: auto; "
        "border: 1px solid #334155; border-radius: 8px; "
        "background: #1a1a2e; }\n"
        "svg { display: block; }\n"
        ".comp { cursor: pointer; transition: opacity 0.15s; }\n"
        ".comp:hover rect { stroke-width: 2.5; stroke: #fff; }\n"
        ".comp.dimmed { opacity: 0.15; }\n"
        ".comp.highlighted rect { stroke: #fbbf24; stroke-width: 3; }\n"
        "#tooltip { position: fixed; background: #1e293b; "
        "border: 1px solid #475569; border-radius: 6px; padding: 8px 12px; "
        "font-size: 0.8rem; pointer-events: none; display: none; z-index: 100; "
        "max-width: 280px; box-shadow: 0 4px 12px rgba(0,0,0,0.5); }\n"
        "#tooltip .ref { font-weight: bold; color: #60a5fa; }\n"
        "#tooltip .val { color: #94a3b8; }\n"
        ".legend { display: flex; gap: 12px; margin-top: 8px; "
        "flex-wrap: wrap; }\n"
        ".legend-item { display: flex; align-items: center; gap: 4px; "
        "font-size: 0.75rem; color: #94a3b8; }\n"
        ".legend-swatch { width: 12px; height: 12px; border-radius: 2px; }\n"
        ".stats { margin-top: 12px; font-size: 0.8rem; color: #64748b; }"
    )

    # Build legend HTML (break generator into variable)
    legend_items = "".join(
        f'<span class="legend-item"><span class="legend-swatch" style="background:{c}"></span>{cat.title()}</span>'
        for cat, c in _CATEGORY_COLORS.items()
    )

    # Build stats text (break long line into parts)
    stats_text = (
        f"Components: {len(comp_map)} &middot; "
        f"Board: {board_width_mm:.0f} x {board_height_mm:.0f} mm &middot; "
        f"Scale: {scale}px/mm"
    )

    # Build board text (break viewBox into parts)
    svg_viewbox = f"{-pad} {-pad} {svg_w + pad * 2:.0f} {svg_h + pad * 2:.0f}"
    board_text = f"Board: {board_width_mm:.0f} x {board_height_mm:.0f} mm"

    page_html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html_mod.escape(title)}</title>
<style>
{css_styles}
</style>
</head>
<body>
<div class="container">
<h1>{html_mod.escape(title)}</h1>
<div class="toolbar">
  <button onclick="resetView()">Reset View</button>
  <button id="btn-thermal" onclick="toggleThermal()">Thermal Overlay</button>
  <button onclick="exportCSV()">Export CSV</button>
  <span style="color:#64748b; font-size:0.8rem; margin-left:8px;">
    Click component to highlight net &middot; Hover for details
  </span>
</div>
<div class="board-container">
<svg id="board" width="{svg_w + pad * 2:.0f}" height="{svg_h + pad * 2:.0f}"
     viewBox="{svg_viewbox}">
  <rect x="0" y="0" width="{svg_w:.0f}" height="{svg_h:.0f}"
        fill="#1e293b" stroke="#475569" stroke-width="2" rx="4"/>
  <text x="{svg_w / 2:.0f}" y="-8" text-anchor="middle"
        fill="#475569" font-size="11">{board_text}</text>
  <g id="thermal-layer">{thermal_content}</g>
  <g id="comp-layer">{svg_content}</g>
</svg>
</div>
<div class="legend">
  {legend_items}
</div>
<div class="stats">
  {stats_text}
</div>
</div>
<div id="tooltip"></div>
<script>
const COMPS = {comp_json};
const NETS = {net_json};
const SCALE = {scale};
let thermalOn = false;
let selectedNet = null;

document.querySelectorAll('.comp').forEach(g => {{
  g.addEventListener('mouseenter', e => {{
    const ref = g.dataset.ref;
    const c = COMPS[ref];
    if (!c) return;
    const tip = document.getElementById('tooltip');
    let html = '<span class="ref">' + c.ref + '</span>';
    if (c.value) html += ' <span class="val">' + c.value + '</span>';
    html += '<br>MPN: ' + (c.mpn || 'N/A');
    html += '<br>Footprint: ' + c.footprint;
    html += '<br>Position: (' + c.x.toFixed(1) + ', ' + c.y.toFixed(1) + ') mm';
    html += '<br>Layer: ' + c.layer;
    if (c.pdiss_w > 0) html += '<br>Power: ' + c.pdiss_w.toFixed(2) + 'W';
    tip.innerHTML = html;
    tip.style.display = 'block';
  }});
  g.addEventListener('mousemove', e => {{
    const tip = document.getElementById('tooltip');
    tip.style.left = (e.clientX + 12) + 'px';
    tip.style.top = (e.clientY + 12) + 'px';
  }});
  g.addEventListener('mouseleave', () => {{
    document.getElementById('tooltip').style.display = 'none';
  }});
  g.addEventListener('click', () => {{
    const ref = g.dataset.ref;
    const c = COMPS[ref];
    if (!c || !c.nets.length) return;
    const net = c.nets[0];
    if (selectedNet === net) {{ resetView(); return; }}
    selectedNet = net;
    const refs = new Set(NETS[net] || []);
    document.querySelectorAll('.comp').forEach(el => {{
      el.classList.toggle('dimmed', !refs.has(el.dataset.ref));
      el.classList.toggle('highlighted', refs.has(el.dataset.ref));
    }});
  }});
}});

function resetView() {{
  selectedNet = null;
  document.querySelectorAll('.comp').forEach(el => {{
    el.classList.remove('dimmed', 'highlighted');
  }});
}}

function toggleThermal() {{
  thermalOn = !thermalOn;
  document.getElementById('btn-thermal').classList.toggle('active', thermalOn);
  document.querySelectorAll('.thermal-overlay').forEach(el => {{
    el.style.display = thermalOn ? 'block' : 'none';
  }});
}}

function exportCSV() {{
  let csv = 'Designator,Mid X,Mid Y,Rotation,Layer\\n';
  for (const [ref, c] of Object.entries(COMPS)) {{
    csv += ref + ',' + c.x.toFixed(2) + ',' + c.y.toFixed(2) + ',' + c.rotation + ',' + c.layer + '\\n';
  }}
  const blob = new Blob([csv], {{type: 'text/csv'}});
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = 'placement.csv';
  a.click();
}}
</script>
</body>
</html>"""

    if output_path:
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(page_html, encoding="utf-8")

    return page_html
