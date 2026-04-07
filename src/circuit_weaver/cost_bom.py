"""Generate a costed BOM with LCSC pricing at volume breaks.

Usage:
    from circuit_weaver.cost_bom import cost_bom
    result = cost_bom(spec, qty_breaks=[1, 10, 100, 1000])
    # result contains rows, totals, warnings
"""

from __future__ import annotations

import logging

from .component_db import ComponentDef
from .dispatcher import compile_design_ir
from .parts_lookup import PartsLookup, get_unit_price

log = logging.getLogger(__name__)


def cost_bom(
    spec: dict,
    qty_breaks: list[int] | None = None,
) -> dict:
    """Return a costed BOM with LCSC pricing at multiple quantity breaks.

    Args:
        spec: Design spec dict (YAML-loaded).
        qty_breaks: List of build quantities to price at. Defaults to [1, 10, 100, 1000].

    Returns:
        {
            "status": "ok" | "error",
            "project": str,
            "qty_breaks": [1, 10, 100, 1000],
            "rows": [
                {
                    "ref": "U1",
                    "mpn": "AP62300",
                    "lcsc_pn": "C460320",
                    "description": "...",
                    "qty_per_board": 1,
                    "stock": 4200,
                    "prices": {
                        "1": {"unit": 0.52, "extended": 0.52},
                        "10": {"unit": 0.43, "extended": 4.30},
                        ...
                    },
                    "status": "ok" | "no_lcsc" | "lookup_failed" | "out_of_stock",
                }
            ],
            "totals": {
                "1": {"component_cost": 12.45, "board_count": 1},
                "10": {"component_cost": 9.81, "board_count": 10},
                ...
            },
            "warnings": [...],
        }
    """
    if qty_breaks is None:
        qty_breaks = [1, 10, 100, 1000]

    qty_breaks = sorted(set(qty_breaks))  # deduplicate and sort

    # Compile the design
    try:
        compiled = compile_design_ir(spec)
    except Exception as e:
        return {
            "status": "error",
            "message": f"Failed to compile spec: {e}",
            "project": spec.get("project", "Unknown"),
        }

    project_name = spec.get("project", "Unknown")
    components = compiled.components

    # Group components by (mpn, lcsc_pn) to match BOM grouping logic
    # Key: (mpn or lcsc, lcsc_pn)
    groups: dict[tuple, list[ComponentDef]] = {}
    for comp in components:
        # Skip components without designators (support passives like bypass caps)
        if not comp.source_ref:
            continue

        key = (comp.source_mpn or comp.mpn or "", comp.lcsc_pn or "")
        if key not in groups:
            groups[key] = []
        groups[key].append(comp)

    # Build rows
    rows = []
    lookup = PartsLookup()
    total_by_qty = {str(q): 0.0 for q in qty_breaks}
    warnings = []

    for (mpn, lcsc_pn), group_comps in groups.items():
        ref_list = ",".join(sorted(set(c.source_ref for c in group_comps)))
        qty_per_board = len(group_comps)
        description = group_comps[0].description or group_comps[0].value or ""

        # Determine what to search for
        search_term = mpn or lcsc_pn
        if not search_term:
            warnings.append(f"No MPN or LCSC code for {ref_list}")
            rows.append(
                {
                    "ref": ref_list,
                    "mpn": "",
                    "lcsc_pn": "",
                    "description": description,
                    "qty_per_board": qty_per_board,
                    "stock": 0,
                    "prices": {str(q): {"unit": 0, "extended": 0} for q in qty_breaks},
                    "status": "no_lcsc",
                }
            )
            continue

        # Look up the part
        lookup_result = lookup.lookup(search_term)
        if not lookup_result:
            warnings.append(f"LCSC lookup failed for {search_term} (refs: {ref_list})")
            rows.append(
                {
                    "ref": ref_list,
                    "mpn": mpn or "",
                    "lcsc_pn": lcsc_pn or "",
                    "description": description,
                    "qty_per_board": qty_per_board,
                    "stock": 0,
                    "prices": {str(q): {"unit": 0, "extended": 0} for q in qty_breaks},
                    "status": "lookup_failed",
                }
            )
            continue

        # Extract pricing tiers
        price_tiers = lookup_result.get("price_tiers") or []
        stock = lookup_result.get("stock", 0)

        # Determine status
        row_status = "ok"
        if not lcsc_pn:
            row_status = "no_lcsc"
        elif stock == 0:
            row_status = "out_of_stock"

        # Compute prices at each qty break
        prices_dict = {}
        for qty_break in qty_breaks:
            qty_needed = qty_per_board * qty_break
            unit_price = get_unit_price(price_tiers, qty_needed) or 0.0
            extended = unit_price * qty_needed
            prices_dict[str(qty_break)] = {
                "unit": round(unit_price, 4),
                "extended": round(extended, 2),
            }
            total_by_qty[str(qty_break)] += extended

        rows.append(
            {
                "ref": ref_list,
                "mpn": mpn or lookup_result.get("mpn", ""),
                "lcsc_pn": lcsc_pn or lookup_result.get("lcsc", ""),
                "description": description,
                "qty_per_board": qty_per_board,
                "stock": stock,
                "prices": prices_dict,
                "status": row_status,
            }
        )

    # Build totals
    totals = {}
    for i, qty_break in enumerate(qty_breaks):
        totals[str(qty_break)] = {
            "component_cost": round(total_by_qty[str(qty_break)], 2),
            "board_count": qty_break,
        }

    return {
        "status": "ok",
        "project": project_name,
        "qty_breaks": qty_breaks,
        "rows": rows,
        "totals": totals,
        "warnings": warnings,
    }
