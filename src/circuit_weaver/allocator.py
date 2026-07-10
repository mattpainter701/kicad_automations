"""Sheet allocator — classifies components by function and assigns to sheets.

Given a list of ComponentDefs, decides:
1. How many sheets are needed
2. What each sheet is called
3. Which components go on which sheet
4. What paper size each sheet needs
"""

import re
from dataclasses import dataclass, field

from .component_db import ComponentDef, PresentationWiringPolicy

# Category -> sheet name mapping (default rules)
CATEGORY_SHEET_MAP = {
    "power": "power",
    "regulator": "power",
    "poe": "power",
    "digital": "mcu",
    "mcu": "mcu",
    "fpga": "fpga",
    "rf": "rf",
    "transceiver": "transceiver",
    "clock": "clock",
    "connector": "connectors",
    "sensor": "sensors",
    "storage": "storage",
    "debug": "debug",
    "communication": "comm",
    "ethernet": "ethernet",
    "usb": "usb",
    "protection": "misc",
    "discrete": "misc",
    "analog": "misc",
    "unknown": "misc",
    "misc": "misc",
    "passive": None,  # passives go with their parent IC
}

# Sheet display names
SHEET_TITLES = {
    "power": "Power Supply",
    "mcu": "MCU / Digital",
    "fpga": "FPGA",
    "rf": "RF Front-End",
    "transceiver": "Transceiver",
    "clock": "Clock",
    "connectors": "Connectors",
    "sensors": "Sensors",
    "storage": "Storage",
    "debug": "Debug & Programming",
    "comm": "Communication",
    "ethernet": "Ethernet",
    "usb": "USB",
    "misc": "Miscellaneous / Discrete",
}


@dataclass
class SheetAllocation:
    """Result of sheet allocation — one sheet's worth of components."""

    name: str  # "power", "mcu", etc.
    title: str  # "Power Supply"
    paper: str  # "A3", "A2", etc.
    components: list = field(default_factory=list)  # list of ComponentDef
    bypass_caps: list = field(default_factory=list)  # auto-generated passives
    straps: list = field(default_factory=list)  # auto-generated straps
    sheet_annotations: list = field(default_factory=list)  # per-sheet description lines
    lock_paper_size: bool = False  # if True, don't optimize paper size; use preset value
    presentation_wiring_policy: PresentationWiringPolicy | None = None
    explicit_group: bool = False  # user-authored section/presentation boundary; never auto-merge

    @property
    def support_part_count(self) -> int:
        """Number of generated two-pin parts that render on this sheet."""
        return len(self.bypass_caps) + len(self.straps)

    @property
    def render_component_count(self) -> int:
        """Total rendered symbols, including generated support parts."""
        return len(self.components) + self.support_part_count

    @property
    def render_pin_count(self) -> int:
        """Approximate rendered pin count used for paper-size planning."""
        return sum(len(comp.pins) for comp in self.components) + 2 * self.support_part_count


def classify_component(comp: ComponentDef) -> str:
    """Determine which sheet a component belongs on."""
    # Use explicit category if set
    if comp.category in CATEGORY_SHEET_MAP:
        sheet = CATEGORY_SHEET_MAP[comp.category]
        if sheet:
            return sheet

    # Infer from ref prefix
    prefix = comp.ref_prefix.upper()
    if prefix in ("J", "P"):
        return "connectors"
    if prefix in ("D",) and "LED" in comp.description.upper():
        return "debug"

    # Infer from description keywords
    desc = comp.description.lower()
    if any(kw in desc for kw in ("regulator", "ldo", "buck", "boost", "pmic")):
        return "power"
    if any(kw in desc for kw in ("mcu", "microcontroller", "soc", "processor")):
        return "mcu"
    if any(kw in desc for kw in ("wifi", "bluetooth", "lora", "zigbee", "rf", "transceiver")):
        return "mcu"  # modules like ESP32 are MCU+radio
    if any(kw in desc for kw in ("fpga", "cpld")):
        return "fpga"
    if any(kw in desc for kw in ("imu", "accel", "gyro", "baro", "temp", "humid", "sensor")):
        return "sensors"
    if any(kw in desc for kw in ("flash", "eeprom", "sd card", "nand", "nor")):
        return "storage"
    if any(kw in desc for kw in ("uart", "usb", "ethernet", "can")):
        return "comm"

    return "misc"  # default: unclassified components go to miscellaneous sheet


def pick_paper_size(num_components: int, total_pins: int) -> str:
    """Pick appropriate paper size based on component/pin density."""
    if num_components <= 5 and total_pins <= 40:
        return "A4"
    if num_components <= 15 and total_pins <= 120:
        return "A3"
    if num_components <= 40 and total_pins <= 300:
        return "A2"
    if num_components <= 80:
        return "A1"
    return "A0"


_PASSIVE_PREFIXES = {"R", "C", "L", "D", "F", "FB", "Y", "FL"}


@dataclass(frozen=True)
class _AllocationGroup:
    key: str
    name: str
    title: str
    explicit: bool = False


def _base_sheet_name(sheet_name: str) -> str:
    return sheet_name.split("_", 1)[0]


def _slug_group_name(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", (name or "").strip().lower()).strip("_")
    return slug or "cluster"


def _group_display_name(name: str) -> str:
    text = (name or "").replace("_", " ").strip()
    return text.title() if text else "Cluster"


def _sheet_name_for_section(section: str) -> str:
    """Normalize a canonical functional section to a stable sheet filename."""
    normalized = re.sub(r"[^a-z0-9]+", "_", (section or "").strip().lower()).strip("_")
    aliases = {
        "communications": "comm",
        "communication": "comm",
        "connectors": "connectors",
        "digital": "mcu",
        "sensing": "sensors",
        "sensor": "sensors",
        "sensors": "sensors",
    }
    if normalized in aliases:
        return aliases[normalized]
    mapped = CATEGORY_SHEET_MAP.get(normalized)
    return mapped or normalized or "misc"


def _allocation_group(comp: ComponentDef) -> _AllocationGroup:
    """Return the functional/presentation group that owns *comp*."""
    presentation_group = (comp.presentation_group or "").strip()
    if presentation_group:
        return _AllocationGroup(
            key=f"presentation:{presentation_group.casefold()}",
            name=_slug_group_name(presentation_group),
            title=_group_display_name(presentation_group),
            explicit=True,
        )

    functional_section = (getattr(comp, "functional_section", "") or "").strip()
    if functional_section:
        name = _sheet_name_for_section(functional_section)
        return _AllocationGroup(
            key=f"sheet:{name}",
            name=name,
            title=SHEET_TITLES.get(name, _group_display_name(functional_section)),
            explicit=True,
        )

    name = classify_component(comp)
    return _AllocationGroup(
        key=f"sheet:{name}",
        name=name,
        title=SHEET_TITLES.get(name, name.title()),
    )


def _render_metrics(components: list[ComponentDef]) -> tuple[int, int]:
    """Return ``(rendered symbols, rendered pins)`` for paper planning."""
    support_count = sum(len(comp.bypass_caps) + len(comp.straps) for comp in components)
    return (
        len(components) + support_count,
        sum(len(comp.pins) for comp in components) + 2 * support_count,
    )


def _paper_for_components(components: list[ComponentDef]) -> str:
    rendered_components, rendered_pins = _render_metrics(components)
    return pick_paper_size(rendered_components, rendered_pins)


def _is_merge_candidate(sheet: SheetAllocation, threshold: int) -> bool:
    """A sheet is a merge candidate if it has only simple passives and no real ICs.

    "No real ICs" means every component has 4 or fewer pins AND uses a
    passive-class reference prefix (R, C, L, D, F, FB, Y, FL).  Sheets
    containing components with an IC-class prefix (U, J, etc.) are kept
    even when small.  The "power" sheet is never a candidate.

    Passive-only sheets are always candidates regardless of count — a sheet
    of 20 standalone resistors still has no reason to be its own page.
    Sheets with a mix of ICs and passives use the threshold.
    """
    if sheet.name == "power":
        return False
    if sheet.explicit_group:
        return False
    all_passive = True
    for comp in sheet.components:
        if len(comp.pins) > 4 or comp.ref_prefix.upper() not in _PASSIVE_PREFIXES:
            all_passive = False
            break
    if all_passive:
        return True  # pure-passive sheets always merge, regardless of count
    return False  # sheets with real ICs are never merge candidates


def _collect_power_nets(sheet: SheetAllocation) -> set[str]:
    """Collect all power net names used by a sheet's components and bypass caps."""
    nets: set[str] = set()
    for comp in sheet.components:
        nets |= comp.all_power_nets()
    for cap in sheet.bypass_caps:
        nets.add(cap.net)
        nets.add(cap.gnd_net)
    return nets


def _sheet_template_annotations(components: list[ComponentDef]) -> list[str]:
    """Collect template-level sheet notes from the sheet's primary components."""
    annotations: list[str] = []
    seen: set[str] = set()
    for comp in components:
        for line in getattr(comp, "template_annotations", []):
            if line and line not in seen:
                seen.add(line)
                annotations.append(line)
    return annotations


def _find_merge_target(candidate: SheetAllocation, sheets: list[SheetAllocation]) -> SheetAllocation | None:
    """Find the best sheet to absorb a tiny candidate.

    Strategy:
    1. Match on shared power nets with another (non-candidate-sized) sheet.
    2. Fallback: the "power" sheet if it exists.
    3. Last resort: the sheet with the most components.
    """
    cand_nets = _collect_power_nets(candidate)

    best_target = None
    best_overlap = 0

    for sheet in sheets:
        if sheet is candidate:
            continue
        overlap = len(cand_nets & _collect_power_nets(sheet))
        if overlap > best_overlap:
            best_overlap = overlap
            best_target = sheet

    if best_target is not None:
        return best_target

    # Fallback: power sheet
    for sheet in sheets:
        if sheet.name == "power":
            return sheet

    # Last resort: largest sheet
    largest = None
    for sheet in sheets:
        if sheet is candidate:
            continue
        if largest is None or len(sheet.components) > len(largest.components):
            largest = sheet
    return largest


def _merge_candidates(sheets: list[SheetAllocation], threshold: int) -> None:
    """Merge tiny passive-only sheets into related sheets, in-place."""
    # Collect candidates first (iterate a copy so we can remove from the original).
    candidates = [s for s in sheets if _is_merge_candidate(s, threshold)]

    for cand in candidates:
        if cand not in sheets:
            continue  # already removed in a prior iteration
        target = _find_merge_target(cand, sheets)
        if target is None or target is cand:
            continue
        # Move everything from candidate into target
        target.components.extend(cand.components)
        target.bypass_caps.extend(cand.bypass_caps)
        target.straps.extend(cand.straps)
        target.sheet_annotations.extend(cand.sheet_annotations)

        # Recalculate paper size for the enlarged target, including support parts.
        target.paper = _paper_for_components(target.components)

        print(f"  Merged '{cand.name}' ({len(cand.components)} parts) into '{target.name}'")
        sheets.remove(cand)


def _review_partition_groups(sheet: SheetAllocation) -> list[tuple[str, list[ComponentDef]]]:
    groups: dict[str, list[ComponentDef]] = {}
    ordered_names: list[str] = []
    for comp in sheet.components:
        group_name = (comp.presentation_group or "").strip()
        if not group_name:
            group_name = "__default__"
        if group_name not in groups:
            groups[group_name] = []
            ordered_names.append(group_name)
        groups[group_name].append(comp)
    return [(name, groups[name]) for name in ordered_names]


def _should_partition_for_review(sheet: SheetAllocation) -> bool:
    groups = _review_partition_groups(sheet)
    return len(groups) >= 2


def _partition_sheet_for_review(sheet: SheetAllocation) -> list[SheetAllocation]:
    if not _should_partition_for_review(sheet):
        return [sheet]

    groups = _review_partition_groups(sheet)
    ranked = sorted(
        groups,
        key=lambda item: (
            -_render_metrics(item[1])[1],
            -_render_metrics(item[1])[0],
            item[0],
        ),
    )

    partitioned: list[SheetAllocation] = []
    for idx, (group_name, comps) in enumerate(ranked):
        all_bypass = []
        all_straps = []
        for comp in comps:
            all_bypass.extend(comp.bypass_caps)
            all_straps.extend(comp.straps)

        if idx == 0:
            name = sheet.name
            title = sheet.title
            annotations = list(dict.fromkeys([*sheet.sheet_annotations, *_sheet_template_annotations(comps)]))
        else:
            suffix = _slug_group_name(group_name)
            name = f"{sheet.name}_{suffix}"
            title = f"{sheet.title} — {_group_display_name(group_name)}"
            annotations = _sheet_template_annotations(comps)

        partitioned.append(
            SheetAllocation(
                name=name,
                title=title,
                paper=sheet.paper if sheet.lock_paper_size else _paper_for_components(comps),
                components=list(comps),
                bypass_caps=all_bypass,
                straps=all_straps,
                sheet_annotations=annotations,
                lock_paper_size=sheet.lock_paper_size,
                presentation_wiring_policy=sheet.presentation_wiring_policy,
                explicit_group=True,
            )
        )

    print(
        f"  Partitioned '{sheet.name}' into "
        + ", ".join(f"{part.name} ({len(part.components)} parts)" for part in partitioned)
    )
    return partitioned


def partition_review_sheets(sheets: list[SheetAllocation]) -> list[SheetAllocation]:
    """Split sheets by declared presentation groups regardless of design size."""
    result: list[SheetAllocation] = []
    for sheet in sheets:
        result.extend(_partition_sheet_for_review(sheet))
    return result


def allocate_sheets(components: list[ComponentDef], single_sheet_threshold: int = 8) -> list[SheetAllocation]:
    """Allocate components to schematic sheets.

    Small legacy designs remain on one sheet. Explicit functional sections or
    presentation groups always win over that shortcut, allowing a compact
    professional design to retain its architectural page boundaries.
    """
    if not components:
        return []

    allocation_groups = [_allocation_group(comp) for comp in components]
    distinct_group_keys = {group.key for group in allocation_groups}
    force_functional_partition = any(group.explicit for group in allocation_groups) and len(distinct_group_keys) > 1

    # Small ungrouped designs: everything on one sheet.
    if len(components) <= single_sheet_threshold and not force_functional_partition:
        all_bypass = []
        all_straps = []
        for c in components:
            all_bypass.extend(c.bypass_caps)
            all_straps.extend(c.straps)
        return [
            SheetAllocation(
                name="main",
                title="Schematic",
                paper=_paper_for_components(components),
                components=list(components),
                bypass_caps=all_bypass,
                straps=all_straps,
                sheet_annotations=_sheet_template_annotations(components),
            )
        ]

    # Larger or explicitly grouped designs: group by presentation/section/category.
    sheets_map: dict[str, tuple[_AllocationGroup, list[ComponentDef]]] = {}
    for comp, group in zip(components, allocation_groups):
        if group.key not in sheets_map:
            sheets_map[group.key] = (group, [])
        sheets_map[group.key][1].append(comp)

    # Build SheetAllocation objects
    result = []
    used_names: set[str] = set()
    for group, comps in sheets_map.values():
        all_bypass = []
        all_straps = []
        for c in comps:
            all_bypass.extend(c.bypass_caps)
            all_straps.extend(c.straps)

        base_name = group.name
        sheet_name = base_name
        suffix = 2
        while sheet_name in used_names:
            sheet_name = f"{base_name}_{suffix}"
            suffix += 1
        used_names.add(sheet_name)

        result.append(
            SheetAllocation(
                name=sheet_name,
                title=group.title,
                paper=_paper_for_components(comps),
                components=comps,
                bypass_caps=all_bypass,
                straps=all_straps,
                sheet_annotations=_sheet_template_annotations(comps),
                explicit_group=group.explicit,
            )
        )

    # Tiny-sheet merge pass: fold sheets with only a few simple passives
    # into a related sheet so we don't generate nearly-empty pages.
    MERGE_THRESHOLD = 3
    _merge_candidates(result, MERGE_THRESHOLD)
    result = partition_review_sheets(result)

    # Sort: power first, then by functional group
    order = {
        "power": 0,
        "transceiver": 1,
        "fpga": 2,
        "clock": 3,
        "mcu": 4,
        "usb": 5,
        "ethernet": 6,
        "rf": 7,
        "sensors": 8,
        "comm": 9,
        "connectors": 10,
        "storage": 11,
        "debug": 12,
    }
    result.sort(key=lambda s: (order.get(_base_sheet_name(s.name), 99), s.name))
    return result
