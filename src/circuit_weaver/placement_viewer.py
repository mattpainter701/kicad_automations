"""Interactive PCB placement viewer — generates an HTML/SVG page.

Features: click-to-highlight nets, hover for component info, thermal heatmap
overlay, DFM clearance display, and CSV placement export.

Usage:
    from circuit_weaver.placement_viewer import generate_viewer
    html = generate_viewer(components, placements, board_width=100, board_height=80)
"""

from __future__ import annotations

import hashlib
import html as html_mod
import json
from pathlib import Path

from .component_db import ComponentDef
from .placement_optimizer import component_part_number, estimate_component_size

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
    placement_context: dict | None = None,
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
        placement_context: Optional machine-readable placement brief including
            inferred rules, research prompts, and authoritative references.
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
        estimated_w, estimated_h = estimate_component_size(comp)
        w = float(p.get("width_mm", estimated_w))
        h = float(p.get("height_mm", estimated_h))
        cat = (comp.category or "other").lower()
        mpn = component_part_number(comp)
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
            "locked": bool(p.get("locked", False)),
            "constraint_locked": bool(p.get("constraint_locked", False)),
            "width": w,
            "height": h,
            "color": _CATEGORY_COLORS.get(cat, "#737373"),
            "pdiss_w": pdiss,
            "nets": [n for n in (comp.pin_nets or {}).values() if n],
            "parent_ref": str(getattr(comp, "placement_parent_ref", "") or ""),
            "placement_role": str(getattr(comp, "placement_role", "") or ""),
            "sourcing_status": str(
                getattr(comp, "placement_sourcing_status", "unspecified") or "unspecified"
            ),
            "geometry_status": str(
                p.get(
                    "geometry_status",
                    getattr(comp, "placement_geometry_status", "estimated"),
                )
                or "estimated"
            ),
        }

    max_pdiss = max((c["pdiss_w"] for c in comp_map.values()), default=0)

    # Build net map for highlighting
    net_components: dict[str, list[str]] = {}
    for ref, data in comp_map.items():
        for net in data["nets"]:
            if net not in net_components:
                net_components[net] = []
            net_components[net].append(ref)

    # Avoid closing the script element when user-controlled part metadata is
    # embedded in the self-contained viewer.
    constraint_evaluation = (
        placement_context.get("constraint_evaluation", {}) if placement_context else {}
    )
    keepouts = [
        keepout
        for keepout in constraint_evaluation.get("keepouts", [])
        if isinstance(keepout, dict)
    ]
    comp_json = json.dumps(comp_map, ensure_ascii=False).replace("</", "<\\/")
    net_json = json.dumps(net_components, ensure_ascii=False).replace("</", "<\\/")
    keepout_json = json.dumps(keepouts, ensure_ascii=False).replace("</", "<\\/")
    fingerprint_rows = [
        {
            key: value
            for key, value in component.items()
            if key
            in {
                "ref",
                "value",
                "mpn",
                "footprint",
                "category",
                "width",
                "height",
                "nets",
                "parent_ref",
                "placement_role",
                "constraint_locked",
                "sourcing_status",
                "geometry_status",
            }
        }
        for _ref, component in sorted(comp_map.items())
    ]
    fingerprint_payload = {
        "board": {"width_mm": board_width_mm, "height_mm": board_height_mm},
        "components": fingerprint_rows,
        "applied_constraints": constraint_evaluation.get("applied", []),
        "keepouts": keepouts,
    }
    design_fingerprint = hashlib.sha256(
        json.dumps(fingerprint_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()

    # Generate SVG component rects
    svg_rects = []
    for ref, c in comp_map.items():
        x = c["x"] * scale
        y = c["y"] * scale
        w = c["width"] * scale
        h = c["height"] * scale
        color = c["color"]
        label = html_mod.escape(ref)

        svg_rects.append(
            f'<g class="comp" data-ref="{html_mod.escape(ref)}" '
            f'data-layer="{html_mod.escape(str(c["layer"]))}" '
            f'transform="translate({x:.1f},{y:.1f}) rotate({c["rotation"]})">'
            f'<rect x="{-w / 2:.1f}" y="{-h / 2:.1f}" width="{w:.1f}" height="{h:.1f}" '
            f'fill="{color}" fill-opacity="0.7" stroke="{color}" stroke-width="1" rx="1"/>'
            f'<text x="0" y="0" text-anchor="middle" dominant-baseline="central" '
            f'transform="rotate({-float(c["rotation"]):g})" '
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
    keepout_content = "\n".join(
        (
            '<g class="keepout" data-keepout="{identifier}">'
            '<rect x="{x:.2f}" y="{y:.2f}" width="{width:.2f}" height="{height:.2f}"/>'
            '<text x="{label_x:.2f}" y="{label_y:.2f}">{label}</text></g>'
        ).format(
            identifier=html_mod.escape(str(keepout.get("id", "keepout")), quote=True),
            x=float(keepout.get("x_mm", 0)) * scale,
            y=float(keepout.get("y_mm", 0)) * scale,
            width=float(keepout.get("width_mm", 0)) * scale,
            height=float(keepout.get("height_mm", 0)) * scale,
            label_x=float(keepout.get("x_mm", 0)) * scale + 4,
            label_y=float(keepout.get("y_mm", 0)) * scale + 12,
            label=html_mod.escape(str(keepout.get("id", "Keepout"))),
        )
        for keepout in keepouts
    )

    context_html = ""
    if placement_context:
        review_gate = placement_context.get("review_gate", {})
        blocker_items = "".join(
            "<li><strong>{target}</strong> {reason}</li>".format(
                target=html_mod.escape(str(blocker.get("target", "Review"))),
                reason=html_mod.escape(str(blocker.get("reason", ""))),
            )
            for blocker in review_gate.get("blockers", [])
        )
        constraint_items = "".join(
            "<li><strong>{kind}</strong> {target}</li>".format(
                kind=html_mod.escape(str(item.get("kind", "constraint")).upper()),
                target=html_mod.escape(str(item.get("target") or item.get("id") or "board")),
            )
            for item in constraint_evaluation.get("applied", [])
        )
        rule_items = "".join(
            "<li><strong>{priority}</strong> {guidance}</li>".format(
                priority=html_mod.escape(str(rule.get("priority", "review")).upper()),
                guidance=html_mod.escape(str(rule.get("guidance", ""))),
            )
            for rule in placement_context.get("rules", [])[:10]
        )
        reference_items = "".join(
            '<li><a href="{url}" target="_blank" rel="noopener noreferrer">{title}</a>'
            '<span>{why}</span></li>'.format(
                url=html_mod.escape(str(reference.get("url", "")), quote=True),
                title=html_mod.escape(str(reference.get("title", "Reference layout"))),
                why=html_mod.escape(str(reference.get("why", ""))),
            )
            for reference in placement_context.get("references", [])
        )
        research_items = "".join(
            "<li><code>{query}</code></li>".format(query=html_mod.escape(str(item.get("query", ""))))
            for item in placement_context.get("research_queries", [])[:8]
        )
        context_html = (
            '<aside class="context-panel"><h2>Placement brief</h2>'
            '<p class="authority">'
            + html_mod.escape(str(placement_context.get("authority", "Heuristic review aid.")))
            + "</p>"
            + (
                f'<h3 class="review-blocked">Review blockers ({len(review_gate.get("blockers", []))})</h3>'
                f'<ul class="review-blocked">{blocker_items}</ul>'
                if blocker_items
                else ""
            )
            + (f"<h3>Applied constraints</h3><ul>{constraint_items}</ul>" if constraint_items else "")
            + (f"<h3>Inferred rules</h3><ul>{rule_items}</ul>" if rule_items else "")
            + (f"<h3>Official examples</h3><ul class=\"references\">{reference_items}</ul>" if reference_items else "")
            + (f"<h3>Part-specific research</h3><ul>{research_items}</ul>" if research_items else "")
            + "</aside>"
        )

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
        ".toolbar select { padding: 6px 10px; border: 1px solid #334155; border-radius: 6px; "
        "background: #1e293b; color: #e2e8f0; max-width: 210px; }\n"
        ".workspace { display: grid; grid-template-columns: minmax(0, 1fr) 320px; gap: 12px; }\n"
        ".workspace.no-context { grid-template-columns: 1fr; }\n"
        ".board-container { position: relative; overflow: auto; "
        "border: 1px solid #334155; border-radius: 8px; "
        "background: #1a1a2e; }\n"
        "svg { display: block; }\n"
        ".comp { cursor: move; transition: opacity 0.15s; touch-action: none; }\n"
        ".comp:hover rect { stroke-width: 2.5; stroke: #fff; }\n"
        ".comp.dimmed { opacity: 0.15; }\n"
        ".comp.highlighted rect { stroke: #fbbf24; stroke-width: 3; }\n"
        ".comp.selected rect { stroke: #22d3ee; stroke-width: 3; }\n"
        ".comp.locked rect { stroke-dasharray: 5 2; }\n"
        ".comp.constraint-locked rect { stroke: #fbbf24; stroke-width: 2.5; }\n"
        ".comp.placeholder rect { fill: #701a75; stroke: #f0abfc; stroke-width: 3; "
        "stroke-dasharray: 3 2; }\n"
        ".comp.back rect { fill-opacity: 0.35; stroke-dasharray: 4 2; }\n"
        ".comp.collision rect { stroke: #ef4444; stroke-width: 3; stroke-dasharray: 3 2; }\n"
        ".ratsnest { stroke: #38bdf8; stroke-opacity: 0.28; stroke-width: 1; pointer-events: none; }\n"
        ".keepout { pointer-events: none; }\n"
        ".keepout rect { fill: #ef4444; fill-opacity: 0.12; stroke: #ef4444; "
        "stroke-width: 1.5; stroke-dasharray: 6 3; }\n"
        ".keepout text { fill: #fca5a5; font-size: 10px; font-weight: 700; }\n"
        ".context-panel { max-height: 760px; overflow: auto; background: #111827; border: 1px solid #334155; "
        "border-radius: 8px; padding: 12px; font-size: 0.78rem; }\n"
        ".context-panel h2 { font-size: 1rem; color: #cbd5e1; margin-bottom: 6px; }\n"
        ".context-panel h3 { font-size: 0.82rem; color: #7dd3fc; margin: 12px 0 5px; }\n"
        ".context-panel ul { padding-left: 18px; display: grid; gap: 5px; }\n"
        ".context-panel .authority { color: #fbbf24; line-height: 1.35; }\n"
        ".context-panel .review-blocked { color: #fca5a5; }\n"
        ".context-panel a { color: #7dd3fc; }\n"
        ".context-panel .references span { display: block; color: #94a3b8; }\n"
        ".context-panel code { white-space: normal; color: #c4b5fd; }\n"
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
        ".stats { margin-top: 12px; font-size: 0.8rem; color: #64748b; }\n"
        "#placement-status.warning { color: #fca5a5; }\n"
        "@media (max-width: 1000px) { .workspace { grid-template-columns: 1fr; } "
        ".context-panel { max-height: none; } }"
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

    js_code = r"""
const COMPS = __COMP_JSON__;
const NETS = __NET_JSON__;
const KEEPOUTS = __KEEPOUT_JSON__;
const SCALE = __SCALE__;
const BOARD_W = __BOARD_W__;
const BOARD_H = __BOARD_H__;
const INITIAL = JSON.parse(JSON.stringify(COMPS));
const STORAGE_KEY = 'circuit-weaver-placement:' + location.pathname + ':' + document.title;
const DESIGN_FINGERPRINT = '__DESIGN_FINGERPRINT__';
const board = document.getElementById('board');
let thermalOn = false;
let connectionsOn = true;
let selectedNet = null;
let selectedRef = null;
let dragState = null;

function svgPoint(event) {
  const point = board.createSVGPoint();
  point.x = event.clientX;
  point.y = event.clientY;
  const matrix = board.getScreenCTM();
  return matrix ? point.matrixTransform(matrix.inverse()) : point;
}

function dimensions(c) {
  const quarterTurns = Math.round(Number(c.rotation || 0) / 90) % 2;
  return quarterTurns ? [c.height, c.width] : [c.width, c.height];
}

function clampComponent(c) {
  const [width, height] = dimensions(c);
  c.x = Math.max(width / 2, Math.min(BOARD_W - width / 2, Number(c.x)));
  c.y = Math.max(height / 2, Math.min(BOARD_H - height / 2, Number(c.y)));
}

function renderComponent(ref) {
  const c = COMPS[ref];
  const group = document.querySelector('.comp[data-ref="' + CSS.escape(ref) + '"]');
  if (!c || !group) return;
  group.setAttribute('transform', 'translate(' + (c.x * SCALE).toFixed(2) + ',' +
    (c.y * SCALE).toFixed(2) + ') rotate(' + Number(c.rotation || 0) + ')');
  const label = group.querySelector('text');
  if (label) label.setAttribute('transform', 'rotate(' + (-Number(c.rotation || 0)) + ')');
  group.dataset.layer = c.layer;
  group.classList.toggle('locked', Boolean(c.locked));
  group.classList.toggle('constraint-locked', Boolean(c.constraint_locked));
  group.classList.toggle('placeholder', c.geometry_status === 'review_blocked_placeholder');
  group.classList.toggle('back', c.layer === 'back');
  const thermal = document.querySelector('.thermal-overlay[data-ref="' + CSS.escape(ref) + '"]');
  if (thermal) {
    const [width, height] = dimensions(c);
    const w = width * SCALE + 4;
    const h = height * SCALE + 4;
    thermal.setAttribute('x', (c.x * SCALE - w / 2).toFixed(2));
    thermal.setAttribute('y', (c.y * SCALE - h / 2).toFixed(2));
    thermal.setAttribute('width', w.toFixed(2));
    thermal.setAttribute('height', h.toFixed(2));
  }
}

function renderAll() {
  Object.keys(COMPS).forEach(renderComponent);
  drawConnections();
  updateQuality();
}

function drawConnections() {
  const layer = document.getElementById('connections-layer');
  layer.replaceChildren();
  if (!connectionsOn) return;
  for (const [net, rawRefs] of Object.entries(NETS)) {
    const refs = [...new Set(rawRefs)].filter(ref => COMPS[ref]);
    if (refs.length < 2) continue;
    const anchor = COMPS[refs[0]];
    for (const ref of refs.slice(1)) {
      const target = COMPS[ref];
      const line = document.createElementNS('http://www.w3.org/2000/svg', 'line');
      line.setAttribute('class', 'ratsnest');
      line.dataset.net = net;
      line.setAttribute('x1', (anchor.x * SCALE).toFixed(2));
      line.setAttribute('y1', (anchor.y * SCALE).toFixed(2));
      line.setAttribute('x2', (target.x * SCALE).toFixed(2));
      line.setAttribute('y2', (target.y * SCALE).toFixed(2));
      layer.appendChild(line);
    }
  }
}

function updateQuality() {
  const refs = Object.keys(COMPS);
  const collisions = new Set();
  const keepoutViolations = new Set();
  for (let i = 0; i < refs.length; i += 1) {
    const a = COMPS[refs[i]];
    const [aw, ah] = dimensions(a);
    for (let j = i + 1; j < refs.length; j += 1) {
      const b = COMPS[refs[j]];
      const [bw, bh] = dimensions(b);
      const overlapX = Math.abs(a.x - b.x) < (aw + bw) / 2 + 0.25;
      const overlapY = Math.abs(a.y - b.y) < (ah + bh) / 2 + 0.25;
      if (overlapX && overlapY) {
        collisions.add(refs[i]);
        collisions.add(refs[j]);
      }
    }
    for (const keepout of KEEPOUTS) {
      const intersects = a.x + aw / 2 > keepout.x_mm &&
        a.x - aw / 2 < keepout.x_mm + keepout.width_mm &&
        a.y + ah / 2 > keepout.y_mm &&
        a.y - ah / 2 < keepout.y_mm + keepout.height_mm;
      if (intersects) keepoutViolations.add(refs[i]);
    }
  }
  document.querySelectorAll('.comp').forEach(group => {
    group.classList.toggle('collision',
      collisions.has(group.dataset.ref) || keepoutViolations.has(group.dataset.ref));
  });
  const status = document.getElementById('placement-status');
  const messages = [];
  if (collisions.size) messages.push(collisions.size + ' components need overlap review');
  if (keepoutViolations.size) messages.push(keepoutViolations.size + ' components violate keepouts');
  status.textContent = messages.length ? messages.join(' · ') : 'No bounding-box or keepout overlaps';
  status.classList.toggle('warning', messages.length > 0);
}

function saveLocal() {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify({
      schema_version: 1,
      design_fingerprint: DESIGN_FINGERPRINT,
      components: COMPS
    }));
  } catch (_error) {
    // The viewer remains fully usable when local storage is disabled.
  }
}

function restoreLocal() {
  try {
    const saved = JSON.parse(localStorage.getItem(STORAGE_KEY) || 'null');
    if (!saved || saved.design_fingerprint !== DESIGN_FINGERPRINT || !saved.components) return;
    const savedRefs = Object.keys(saved.components).sort();
    const currentRefs = Object.keys(COMPS).sort();
    if (savedRefs.length !== currentRefs.length || savedRefs.some((ref, i) => ref !== currentRefs[i])) return;
    for (const [ref, placement] of Object.entries(saved.components)) {
      if (!COMPS[ref]) continue;
      if (COMPS[ref].constraint_locked) continue;
      for (const field of ['x', 'y', 'rotation', 'layer', 'locked']) {
        if (field in placement) COMPS[ref][field] = placement[field];
      }
      clampComponent(COMPS[ref]);
    }
  } catch (_error) {
    // Ignore stale or malformed browser state.
  }
}

function selectComponent(ref) {
  selectedRef = ref;
  document.querySelectorAll('.comp').forEach(group => {
    group.classList.toggle('selected', group.dataset.ref === ref);
  });
}

function highlightNet(net) {
  selectedNet = net || null;
  const refs = new Set(selectedNet ? (NETS[selectedNet] || []) : []);
  document.querySelectorAll('.comp').forEach(group => {
    group.classList.toggle('dimmed', Boolean(selectedNet) && !refs.has(group.dataset.ref));
    group.classList.toggle('highlighted', Boolean(selectedNet) && refs.has(group.dataset.ref));
  });
  document.querySelectorAll('.ratsnest').forEach(line => {
    line.style.strokeOpacity = selectedNet ? (line.dataset.net === selectedNet ? '0.9' : '0.05') : '0.28';
  });
  document.getElementById('net-select').value = selectedNet || '';
}

function resetView() {
  highlightNet('');
  selectComponent(null);
}

function resetPlacement() {
  for (const [ref, placement] of Object.entries(INITIAL)) {
    Object.assign(COMPS[ref], JSON.parse(JSON.stringify(placement)));
  }
  try { localStorage.removeItem(STORAGE_KEY); } catch (_error) {}
  resetView();
  renderAll();
}

function toggleConnections() {
  connectionsOn = !connectionsOn;
  document.getElementById('btn-connections').classList.toggle('active', connectionsOn);
  drawConnections();
  if (selectedNet) highlightNet(selectedNet);
}

function toggleThermal() {
  thermalOn = !thermalOn;
  document.getElementById('btn-thermal').classList.toggle('active', thermalOn);
  document.querySelectorAll('.thermal-overlay').forEach(element => {
    element.style.display = thermalOn ? 'block' : 'none';
  });
}

function toggleLock() {
  if (!selectedRef || !COMPS[selectedRef]) return;
  if (COMPS[selectedRef].constraint_locked) return;
  COMPS[selectedRef].locked = !COMPS[selectedRef].locked;
  renderComponent(selectedRef);
  saveLocal();
}

function download(name, type, content) {
  const blob = new Blob([content], {type});
  const anchor = document.createElement('a');
  const url = URL.createObjectURL(blob);
  anchor.href = url;
  anchor.download = name;
  anchor.click();
  setTimeout(() => URL.revokeObjectURL(url), 0);
}

function exportJSON() {
  const placements = {};
  for (const [ref, c] of Object.entries(COMPS)) {
    placements[ref] = {
      x: Number(c.x.toFixed(3)), y: Number(c.y.toFixed(3)),
      rotation: Number(c.rotation || 0), layer: c.layer, locked: Boolean(c.locked)
    };
  }
  const payload = {schema_version: 1, artifact_kind: 'placement_edits', units: 'mm', placements};
  download('placement.json', 'application/json', JSON.stringify(payload, null, 2) + '\n');
}

function csvField(value) {
  const text = String(value ?? '');
  return /[",\n]/.test(text) ? '"' + text.replaceAll('"', '""') + '"' : text;
}

function exportCSV() {
  const rows = [['Designator', 'Mid X', 'Mid Y', 'Rotation', 'Layer']];
  for (const [ref, c] of Object.entries(COMPS)) {
    rows.push([ref, c.x.toFixed(2), c.y.toFixed(2), c.rotation, c.layer]);
  }
  download('placement.csv', 'text/csv', rows.map(row => row.map(csvField).join(',')).join('\n') + '\n');
}

function exportSVG() {
  // Preserve the editable, reference-addressable vector contract consumed by
  // `circuit-weaver import-placement`. Review-only overlays are omitted so
  // this stays a compact placement exchange artifact, not a screenshot.
  const source = document.getElementById('board');
  const clone = source.cloneNode(true);
  clone.setAttribute('xmlns', 'http://www.w3.org/2000/svg');
  clone.setAttribute('data-scale-px-per-mm', String(SCALE));
  const connections = clone.querySelector('#connections-layer');
  const thermal = clone.querySelector('#thermal-layer');
  const constraints = clone.querySelector('#constraints-layer');
  if (connections) connections.remove();
  if (thermal) thermal.remove();
  if (constraints) constraints.remove();
  const xml = new XMLSerializer().serializeToString(clone);
  download('placement.svg', 'image/svg+xml', '<?xml version="1.0" encoding="UTF-8"?>\n' + xml + '\n');
}

function showTooltip(group, event) {
  const c = COMPS[group.dataset.ref];
  if (!c) return;
  const lines = [c.ref + (c.value ? '  ' + c.value : ''), 'MPN: ' + (c.mpn || 'N/A'),
    'Footprint: ' + (c.footprint || 'N/A'),
    'Position: (' + c.x.toFixed(2) + ', ' + c.y.toFixed(2) + ') mm',
    'Rotation: ' + c.rotation + '°  Layer: ' + c.layer,
    'Role: ' + (c.placement_role || c.category) + (c.parent_ref ? ' near ' + c.parent_ref : ''),
    'Sourcing: ' + c.sourcing_status + (c.constraint_locked ? '  Fixed by constraint' : ''),
    'Geometry: ' + c.geometry_status];
  if (c.pdiss_w > 0) lines.push('Power: ' + c.pdiss_w.toFixed(2) + ' W');
  const tip = document.getElementById('tooltip');
  tip.textContent = lines.join('\n');
  tip.style.whiteSpace = 'pre-line';
  tip.style.display = 'block';
  tip.style.left = (event.clientX + 12) + 'px';
  tip.style.top = (event.clientY + 12) + 'px';
}

document.querySelectorAll('.comp').forEach(group => {
  group.addEventListener('mouseenter', event => showTooltip(group, event));
  group.addEventListener('mousemove', event => {
    showTooltip(group, event);
    if (!dragState || dragState.ref !== group.dataset.ref) return;
    const c = COMPS[dragState.ref];
    if (c.locked) return;
    const point = svgPoint(event);
    c.x = point.x / SCALE - dragState.offsetX;
    c.y = point.y / SCALE - dragState.offsetY;
    clampComponent(c);
    dragState.moved = true;
    renderComponent(dragState.ref);
    drawConnections();
    updateQuality();
  });
  group.addEventListener('mouseleave', () => {
    if (!dragState) document.getElementById('tooltip').style.display = 'none';
  });
  group.addEventListener('pointerdown', event => {
    event.preventDefault();
    const ref = group.dataset.ref;
    selectComponent(ref);
    const c = COMPS[ref];
    const point = svgPoint(event);
    dragState = {ref, pointerId: event.pointerId, moved: false,
      offsetX: point.x / SCALE - c.x, offsetY: point.y / SCALE - c.y};
    group.setPointerCapture(event.pointerId);
  });
  group.addEventListener('pointerup', event => {
    if (!dragState || dragState.pointerId !== event.pointerId) return;
    const moved = dragState.moved;
    const ref = dragState.ref;
    dragState = null;
    group.releasePointerCapture(event.pointerId);
    saveLocal();
    if (!moved && COMPS[ref].nets.length) highlightNet(COMPS[ref].nets[0]);
  });
  group.addEventListener('pointercancel', () => { dragState = null; });
});

document.addEventListener('keydown', event => {
  if (!selectedRef || !COMPS[selectedRef]) return;
  const c = COMPS[selectedRef];
  if (event.key.toLowerCase() === 'l') {
    toggleLock();
    return;
  }
  if (c.locked) return;
  let changed = false;
  if (event.key.toLowerCase() === 'r') { c.rotation = (Number(c.rotation || 0) + 90) % 360; changed = true; }
  if (event.key.toLowerCase() === 'f') { c.layer = c.layer === 'front' ? 'back' : 'front'; changed = true; }
  const step = event.shiftKey ? 2.5 : 0.5;
  if (event.key === 'ArrowLeft') { c.x -= step; changed = true; }
  if (event.key === 'ArrowRight') { c.x += step; changed = true; }
  if (event.key === 'ArrowUp') { c.y -= step; changed = true; }
  if (event.key === 'ArrowDown') { c.y += step; changed = true; }
  if (!changed) return;
  event.preventDefault();
  clampComponent(c);
  renderComponent(selectedRef);
  drawConnections();
  updateQuality();
  saveLocal();
});

const netSelect = document.getElementById('net-select');
for (const net of Object.keys(NETS).sort()) {
  const option = document.createElement('option');
  option.value = net;
  option.textContent = net + ' (' + new Set(NETS[net]).size + ')';
  netSelect.appendChild(option);
}

restoreLocal();
renderAll();
document.getElementById('btn-connections').classList.add('active');
"""
    js_code = (
        js_code.replace("__COMP_JSON__", comp_json)
        .replace("__NET_JSON__", net_json)
        .replace("__KEEPOUT_JSON__", keepout_json)
        .replace("__SCALE__", json.dumps(scale))
        .replace("__BOARD_W__", json.dumps(board_width_mm))
        .replace("__BOARD_H__", json.dumps(board_height_mm))
        .replace("__DESIGN_FINGERPRINT__", design_fingerprint)
    )

    workspace_class = "workspace has-context" if context_html else "workspace no-context"

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
  <button onclick="resetPlacement()">Reset Placement</button>
  <button onclick="resetView()">Clear Selection</button>
  <button id="btn-connections" onclick="toggleConnections()">Connections</button>
  <button id="btn-thermal" onclick="toggleThermal()">Thermal Overlay</button>
  <button onclick="toggleLock()">Lock / Unlock</button>
  <button onclick="exportSVG()">Export Editable SVG</button>
  <button onclick="exportJSON()">Export JSON</button>
  <button onclick="exportCSV()">Export CSV</button>
  <select id="net-select" onchange="highlightNet(this.value)"><option value="">All nets</option></select>
  <span style="color:#64748b; font-size:0.8rem; margin-left:8px;">
    Drag to move &middot; R rotate &middot; F flip side &middot; L lock &middot; arrows nudge
  </span>
</div>
<div class="{workspace_class}">
<div class="board-container">
<svg id="board" width="{svg_w + pad * 2:.0f}" height="{svg_h + pad * 2:.0f}"
     viewBox="{svg_viewbox}" data-scale-px-per-mm="{scale}">
  <rect x="0" y="0" width="{svg_w:.0f}" height="{svg_h:.0f}"
        fill="#1e293b" stroke="#475569" stroke-width="2" rx="4"/>
  <text x="{svg_w / 2:.0f}" y="-8" text-anchor="middle"
        fill="#475569" font-size="11">{board_text}</text>
  <g id="constraints-layer">{keepout_content}</g>
  <g id="connections-layer"></g>
  <g id="thermal-layer">{thermal_content}</g>
  <g id="comp-layer">{svg_content}</g>
</svg>
</div>
{context_html}
</div>
<div class="legend">
  {legend_items}
</div>
<div class="stats">
  {stats_text} &middot; <span id="placement-status">Checking placement&hellip;</span>
</div>
</div>
<div id="tooltip"></div>
<script>
{js_code}
</script>
</body>
</html>"""

    if output_path:
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(page_html, encoding="utf-8")

    return page_html
