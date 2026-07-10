"""Machine-readable context for AI-assisted PCB placement review.

The placement optimizer is deliberately heuristic: a part-specific datasheet or
reference layout remains authoritative.  This module makes that boundary
explicit and gives agent workflows a stable artifact containing the proposed
placement, the constraints the engine inferred, and targeted research prompts.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .component_db import ComponentDef
from .placement_optimizer import component_part_number

_GROUND_PREFIXES = ("GND", "AGND", "DGND", "PGND", "VSS")
_POWER_PREFIXES = ("VDD", "VCC", "VBUS", "VIN", "VBAT", "VSYS", "AVDD", "DVDD")
_DIFF_TOKENS = ("USB", "DP", "DM", "D+", "D-", "TXP", "TXN", "RXP", "RXN", "LVDS", "CAN")
_CLOCK_TOKENS = ("CLK", "CLOCK", "XTAL", "OSC")
_SWITCH_TOKENS = ("SW", "PHASE", "LX", "BOOT")


_REFERENCES: dict[str, dict[str, str]] = {
    "power": {
        "title": "Five steps to a great PCB layout for a step-down converter",
        "url": "https://www.ti.com/lit/an/slyt614/slyt614.pdf",
        "publisher": "Texas Instruments",
        "why": "Power-stage ordering, hot-loop minimization, switch-node control, and grounding.",
    },
    "rf": {
        "title": "General PCB design guidelines for nRF52 series",
        "url": "https://devzone.nordicsemi.com/guides/hardware-design-test-and-measuring/b/nrf5x/posts/general-pcb-design-guidelines-for-nrf52",
        "publisher": "Nordic Semiconductor",
        "why": "RF matching, antenna-edge placement, keepouts, and reference-layout fidelity.",
    },
    "usb": {
        "title": "High-Speed Layout Guidelines for Signal Conditioners and USB Hubs",
        "url": "https://www.ti.com/lit/an/slla414a/slla414a.pdf",
        "publisher": "Texas Instruments",
        "why": "Differential-pair routing and ESD/EMI device placement at the connector.",
    },
    "decoupling": {
        "title": "PCB Layout Guide for CEC1712",
        "url": "https://www.microchip.com/content/dam/mchp/documents/CPG/ApplicationNotes/ApplicationNotes/AN3760-Application-Note-DS00003760A.pdf",
        "publisher": "Microchip",
        "why": "Concrete bypass-capacitor, via, crystal, and sensitive-trace placement examples.",
    },
    "oscillator": {
        "title": "AVR186: Best practices for the PCB layout of oscillators",
        "url": "https://www.microchip.com/en-us/application-notes/an8128",
        "publisher": "Microchip",
        "why": "Crystal-loop placement and isolation from noisy circuitry.",
    },
}


def _component_ref(comp: ComponentDef) -> str:
    return str(comp.source_ref or "").strip()


def _component_nets(comp: ComponentDef) -> set[str]:
    nets = set(comp.pin_nets.values()) | set(comp.power_pins.values())
    for cap in comp.bypass_caps:
        nets.update((cap.net, cap.gnd_net))
    for strap in comp.straps:
        nets.update((strap.net, strap.rail))
    return {str(net) for net in nets if net}


def _net_kind(net: str) -> str:
    upper = net.upper()
    if upper.startswith(_GROUND_PREFIXES):
        return "ground"
    if upper.startswith(_POWER_PREFIXES):
        return "power"
    if any(token in upper for token in _DIFF_TOKENS):
        return "high_speed_or_differential"
    if any(token in upper for token in _CLOCK_TOKENS):
        return "clock"
    if any(token == upper or upper.startswith(f"{token}_") for token in _SWITCH_TOKENS):
        return "switching"
    return "signal"


def _reference_keys(components: list[ComponentDef]) -> list[str]:
    categories = {str(comp.category or "").lower() for comp in components}
    all_nets = {net.upper() for comp in components for net in _component_nets(comp)}
    keys = {"decoupling"}
    if categories & {"power", "regulator", "poe"}:
        keys.add("power")
    if categories & {"rf", "transceiver"}:
        keys.add("rf")
    if categories & {"usb"} or any("USB" in net or net.endswith(("_DP", "_DM")) for net in all_nets):
        keys.add("usb")
    if categories & {"clock"} or any(any(token in net for token in _CLOCK_TOKENS) for net in all_nets):
        keys.add("oscillator")
    return sorted(keys)


def _component_official_references(components: list[ComponentDef]) -> list[dict[str, str]]:
    """Expose data-driven official links without inventing vendor evidence."""
    references: list[dict[str, str]] = []
    seen_urls: set[str] = set()
    for comp in sorted(components, key=_component_ref):
        ref = _component_ref(comp)
        candidates: list[dict[str, Any]] = []
        raw_references = getattr(comp, "official_references", [])
        if isinstance(raw_references, list):
            candidates.extend(item for item in raw_references if isinstance(item, dict))
        for attribute, title in (
            ("datasheet_url", "Official datasheet"),
            ("reference_layout_url", "Official reference layout"),
        ):
            url = str(getattr(comp, attribute, "") or "").strip()
            if url:
                candidates.append({"url": url, "title": title})

        for candidate in candidates:
            url = str(candidate.get("url", "") or "").strip()
            parsed = urlparse(url)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc or url in seen_urls:
                continue
            seen_urls.add(url)
            references.append(
                {
                    "topic": "component",
                    "ref": ref,
                    "mpn": component_part_number(comp),
                    "title": str(candidate.get("title") or f"{ref} official reference"),
                    "url": url,
                    "publisher": str(candidate.get("publisher") or "Component manufacturer"),
                    "why": str(
                        candidate.get("why")
                        or "Part-specific placement, land-pattern, keepout, and routing guidance."
                    ),
                    "source": "component_metadata",
                }
            )
    return references


def _placement_rules(components: list[ComponentDef]) -> list[dict[str, Any]]:
    rules: list[dict[str, Any]] = []
    refs = {_component_ref(comp): comp for comp in components if _component_ref(comp)}
    for ref, comp in sorted(refs.items()):
        category = str(comp.category or "other").lower()
        parent_ref = str(getattr(comp, "placement_parent_ref", "") or "")
        role = str(getattr(comp, "placement_role", "") or "")
        if parent_ref:
            rules.append(
                {
                    "kind": "parent_affinity",
                    "targets": [ref, parent_ref],
                    "priority": "critical" if role in {"decoupling", "bootstrap"} else "high",
                    "guidance": "Keep the support part adjacent to its owning IC pin and minimize loop area.",
                }
            )
        if category in {"connector", "usb", "debug"}:
            rules.append(
                {
                    "kind": "edge_access",
                    "targets": [ref],
                    "priority": "high",
                    "guidance": "Place at the mechanically intended edge before optimizing internal circuitry.",
                }
            )
        if category in {"rf", "transceiver"}:
            rules.append(
                {
                    "kind": "rf_keepout",
                    "targets": [ref],
                    "priority": "critical",
                    "guidance": (
                        "Use the vendor reference layout; keep antenna/matching at an edge and away from switchers."
                    ),
                }
            )
        if category in {"power", "regulator", "poe"}:
            rules.append(
                {
                    "kind": "power_hot_loop",
                    "targets": [ref],
                    "priority": "critical",
                    "guidance": (
                        "Place input bypass, switching element, inductor, and output capacitor in datasheet order."
                    ),
                }
            )
    return rules


def _sourcing_record(comp: ComponentDef) -> dict[str, Any]:
    source_kind = str(getattr(comp, "assembly_source_kind", "component") or "component")
    status = str(getattr(comp, "placement_sourcing_status", "") or "")
    part_number = component_part_number(comp)
    lcsc_pn = str(getattr(comp, "lcsc_pn", "") or "").strip()
    manufacturer = str(getattr(comp, "source_manufacturer", "") or "").strip()
    if not status:
        status = "identified" if part_number or lcsc_pn else "unspecified"
    review_blocking = status == "review_blocked"
    reason = str(getattr(comp, "placement_sourcing_review_reason", "") or "")
    return {
        "status": status,
        "review_blocking": review_blocking,
        "source_kind": source_kind,
        "mpn": part_number,
        "manufacturer": manufacturer,
        "lcsc_pn": lcsc_pn,
        "reason": reason,
    }


def build_placement_context(
    components: list[ComponentDef],
    placements: dict[str, dict[str, Any]],
    *,
    board_width_mm: float,
    board_height_mm: float,
    constraints: list[dict[str, Any]] | None = None,
    constraint_evaluation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return a deterministic context bundle for placement review agents."""
    component_rows: list[dict[str, Any]] = []
    groups: dict[str, list[str]] = {}
    net_members: dict[str, list[str]] = {}

    for comp in sorted(components, key=lambda item: _component_ref(item)):
        ref = _component_ref(comp)
        if not ref:
            continue
        category = str(comp.category or "other").lower()
        nets = sorted(_component_nets(comp))
        groups.setdefault(category, []).append(ref)
        for net in nets:
            net_members.setdefault(net, []).append(ref)
        sourcing = _sourcing_record(comp)
        geometry_status = str(
            getattr(comp, "placement_geometry_status", "estimated") or "estimated"
        )
        component_rows.append(
            {
                "ref": ref,
                "mpn": component_part_number(comp),
                "value": comp.value,
                "footprint": comp.footprint,
                "category": category,
                "functional_section": str(getattr(comp, "functional_section", "") or ""),
                "parent_ref": str(getattr(comp, "placement_parent_ref", "") or ""),
                "placement_role": str(getattr(comp, "placement_role", "") or ""),
                "nets": nets,
                "placement": placements.get(ref),
                "sourcing": sourcing,
                "geometry": {
                    "status": geometry_status,
                    "review_blocking": geometry_status == "review_blocked_placeholder",
                    "reason": str(
                        getattr(comp, "placement_geometry_review_reason", "") or ""
                    ),
                },
            }
        )

    critical_nets = [
        {"name": net, "kind": _net_kind(net), "members": sorted(set(refs))}
        for net, refs in sorted(net_members.items())
        if len(set(refs)) > 1 and _net_kind(net) != "signal"
    ]
    research_queries = []
    for row in component_rows:
        if (
            not row["mpn"]
            or row["category"] == "passive"
            or row["parent_ref"]
            or not row["footprint"]
            or row["geometry"]["review_blocking"]
        ):
            continue
        research_queries.append(
            {
                "ref": row["ref"],
                "query": f"{row['mpn']} official datasheet PCB layout reference design EVM Gerber",
                "required_evidence": "Official datasheet or manufacturer reference-layout figure/repository",
            }
        )

    review_blockers = [
        {
            "kind": "sourcing_metadata",
            "target": row["ref"],
            "reason": row["sourcing"]["reason"] or "Part has no traceable sourcing identifier.",
        }
        for row in component_rows
        if row["sourcing"]["review_blocking"]
    ]
    review_blockers.extend(
        {
            "kind": "footprint_geometry",
            "target": row["ref"],
            "reason": row["geometry"]["reason"]
            or "Footprint geometry is a nonphysical placeholder.",
        }
        for row in component_rows
        if row["geometry"]["review_blocking"]
    )
    evaluation = constraint_evaluation or {}
    if evaluation.get("board_dimension_source") == "derived_review":
        review_blockers.insert(
            0,
            {
                "kind": "board_dimensions",
                "target": "board",
                "reason": (
                    "The compact board is an area-derived review canvas, not a verified mechanical "
                    "outline; supply actual board dimensions before placement approval."
                ),
            },
        )
    review_blockers.extend(
        {
            "kind": "placement_constraint",
            "target": str(item.get("target", "")),
            "reason": str(item.get("reason", "Placement constraint needs review.")),
        }
        for item in evaluation.get("unsupported", [])
    )
    review_blockers.extend(
        {
            "kind": "placement_constraint_violation",
            "target": str(item.get("target", "")),
            "reason": str(item.get("reason", "Placement constraint was not satisfied.")),
        }
        for item in evaluation.get("violations", [])
    )

    return {
        "schema_version": 2,
        "artifact_kind": "placement_review_context",
        "authority": (
            "Heuristic review aid only. Part-specific official datasheets and reference layouts are authoritative."
        ),
        "board": {"width_mm": board_width_mm, "height_mm": board_height_mm},
        "components": component_rows,
        "groups": {key: sorted(values) for key, values in sorted(groups.items())},
        "critical_nets": critical_nets,
        "constraints": constraints or [],
        "constraint_evaluation": evaluation,
        "rules": _placement_rules(components),
        "research_queries": research_queries,
        "references": [
            *[_REFERENCES[key] | {"topic": key} for key in _reference_keys(components)],
            *_component_official_references(components),
        ],
        "review_gate": {
            "status": "blocked" if review_blockers else "review_required",
            "blocker_count": len(review_blockers),
            "blockers": review_blockers,
        },
    }


def write_placement_context(context: dict[str, Any], output_path: str | Path) -> Path:
    """Write a placement context bundle as stable, human-readable JSON."""
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(context, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path
