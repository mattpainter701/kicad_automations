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
_REVIEW_PARTITION_MIN_TOTAL_PINS = 220

# Auto-partition thresholds (T195) — when a single sheet exceeds either
# threshold AND has no presentation_group partitioning, split into chunks
# by ref-prefix locality so we don't ship single-A0 monsters.
_AUTO_PARTITION_MAX_COMPONENTS = 18
_AUTO_PARTITION_MAX_PINS = 280
_AUTO_PARTITION_TARGET_COMPONENTS = 12  # target chunk size after partition


def _base_sheet_name(sheet_name: str) -> str:
    return sheet_name.split("_", 1)[0]


def _slug_group_name(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", (name or "").strip().lower()).strip("_")
    return slug or "cluster"


def _group_display_name(name: str) -> str:
    text = (name or "").replace("_", " ").strip()
    return text.title() if text else "Cluster"


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

        # Recalculate paper size for the enlarged target
        total_pins = sum(len(c.pins) for c in target.components)
        target.paper = pick_paper_size(len(target.components), total_pins)

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
    if len(groups) < 2:
        return False
    total_pins = sum(len(comp.pins) for comp in sheet.components)
    return total_pins >= _REVIEW_PARTITION_MIN_TOTAL_PINS


def _partition_sheet_for_review(sheet: SheetAllocation) -> list[SheetAllocation]:
    if not _should_partition_for_review(sheet):
        return [sheet]

    groups = _review_partition_groups(sheet)
    ranked = sorted(
        groups,
        key=lambda item: (
            -sum(len(comp.pins) for comp in item[1]),
            -len(item[1]),
            item[0],
        ),
    )

    partitioned: list[SheetAllocation] = []
    for idx, (group_name, comps) in enumerate(ranked):
        total_pins = sum(len(comp.pins) for comp in comps)
        all_bypass = []
        all_straps = []
        for comp in comps:
            all_bypass.extend(comp.bypass_caps)
            all_straps.extend(comp.straps)

        if idx == 0:
            name = sheet.name
            title = sheet.title
            annotations = list(sheet.sheet_annotations)
        else:
            suffix = _slug_group_name(group_name)
            name = f"{sheet.name}_{suffix}"
            title = f"{sheet.title} — {_group_display_name(group_name)}"
            annotations = []

        partitioned.append(
            SheetAllocation(
                name=name,
                title=title,
                paper=pick_paper_size(len(comps), total_pins),
                components=list(comps),
                bypass_caps=all_bypass,
                straps=all_straps,
                sheet_annotations=annotations,
                presentation_wiring_policy=sheet.presentation_wiring_policy,
            )
        )

    print(
        f"  Partitioned '{sheet.name}' into "
        + ", ".join(f"{part.name} ({len(part.components)} parts)" for part in partitioned)
    )
    return partitioned


def _is_density_overload(sheet: SheetAllocation) -> bool:
    """A sheet is density-overloaded if it would produce an unreadable single sheet."""
    n = len(sheet.components)
    pins = sum(len(c.pins) for c in sheet.components)
    return n > _AUTO_PARTITION_MAX_COMPONENTS or pins > _AUTO_PARTITION_MAX_PINS


def _ref_prefix_bucket(comp: ComponentDef) -> str:
    """Group components by ref-prefix family for locality during auto-partition."""
    prefix = (comp.ref_prefix or "").upper()
    if prefix in {"U", "IC"}:
        return "ic"
    if prefix in {"J", "P", "X"}:
        return "connector"
    if prefix in _PASSIVE_PREFIXES:
        return "passive"
    return "other"


def _auto_partition_dense_sheet(sheet: SheetAllocation) -> list[SheetAllocation]:
    """Split a dense sheet into chunks based on ref-prefix locality.

    Triggered when a sheet exceeds component or pin thresholds and the
    explicit presentation-group partitioner produced no split. Splits the
    sheet into roughly ``_AUTO_PARTITION_TARGET_COMPONENTS``-sized chunks,
    grouping by ref-prefix family (ICs together, connectors together, then
    passives) to preserve visual locality.
    """
    if not _is_density_overload(sheet):
        return [sheet]

    # Bucket components by ref-prefix family, preserving original order within bucket.
    buckets: dict[str, list[ComponentDef]] = {}
    bucket_order: list[str] = []
    for comp in sheet.components:
        bucket = _ref_prefix_bucket(comp)
        if bucket not in buckets:
            buckets[bucket] = []
            bucket_order.append(bucket)
        buckets[bucket].append(comp)

    # Concatenate buckets in a stable order (ICs first, then connectors, then others/passives).
    bucket_priority = {"ic": 0, "connector": 1, "other": 2, "passive": 3}
    ordered_components: list[ComponentDef] = []
    for bucket in sorted(bucket_order, key=lambda b: bucket_priority.get(b, 9)):
        ordered_components.extend(buckets[bucket])

    # Greedy chunking — keep chunks balanced by component count and pin total.
    target = max(1, _AUTO_PARTITION_TARGET_COMPONENTS)
    chunks: list[list[ComponentDef]] = []
    current: list[ComponentDef] = []
    current_pins = 0
    pin_target = max(60, _AUTO_PARTITION_MAX_PINS // 2)
    for comp in ordered_components:
        comp_pins = len(comp.pins)
        if current and (
            len(current) >= target
            or current_pins + comp_pins > pin_target
        ):
            chunks.append(current)
            current = []
            current_pins = 0
        current.append(comp)
        current_pins += comp_pins
    if current:
        chunks.append(current)

    if len(chunks) <= 1:
        return [sheet]

    partitioned: list[SheetAllocation] = []
    for idx, comps in enumerate(chunks):
        chunk_bypass: list = []
        chunk_straps: list = []
        for c in comps:
            chunk_bypass.extend(c.bypass_caps)
            chunk_straps.extend(c.straps)

        if idx == 0:
            name = sheet.name
            title = sheet.title
            annotations = list(sheet.sheet_annotations)
        else:
            name = f"{sheet.name}_{idx + 1}"
            title = f"{sheet.title} (cont. {idx + 1})"
            annotations = []

        total_pins = sum(len(c.pins) for c in comps)
        partitioned.append(
            SheetAllocation(
                name=name,
                title=title,
                paper=pick_paper_size(len(comps), total_pins),
                components=list(comps),
                bypass_caps=chunk_bypass,
                straps=chunk_straps,
                sheet_annotations=annotations,
                presentation_wiring_policy=sheet.presentation_wiring_policy,
            )
        )

    print(
        f"  Auto-partitioned dense sheet '{sheet.name}' "
        f"({len(sheet.components)} parts, {sum(len(c.pins) for c in sheet.components)} pins) into "
        + ", ".join(f"{part.name} ({len(part.components)} parts)" for part in partitioned)
    )
    return partitioned


def partition_review_sheets(sheets: list[SheetAllocation]) -> list[SheetAllocation]:
    """Split very large review sheets, first by declared presentation groups, then by density.

    Two-pass strategy:

    1. Explicit partitioning by `presentation_group` field on components
       (when set, groups are honored verbatim).
    2. Auto-partition fallback: if a sheet still has too many components
       or pins after step 1, split by ref-prefix locality (T195).
    """
    result: list[SheetAllocation] = []
    for sheet in sheets:
        # Step 1: presentation-group partition (existing behavior).
        review_partitions = _partition_sheet_for_review(sheet)

        # Step 2: auto-partition any sub-sheet that's still density-overloaded.
        for sub in review_partitions:
            result.extend(_auto_partition_dense_sheet(sub))
    return result


def allocate_sheets(components: list[ComponentDef], single_sheet_threshold: int = 8) -> list[SheetAllocation]:
    """Allocate components to schematic sheets.

    If total component count is small enough, put everything on one sheet.
    Otherwise, split by category.
    """
    if not components:
        return []

    # Small designs: everything on one sheet
    if len(components) <= single_sheet_threshold:
        total_pins = sum(len(c.pins) for c in components)
        all_bypass = []
        all_straps = []
        for c in components:
            all_bypass.extend(c.bypass_caps)
            all_straps.extend(c.straps)
        return [
            SheetAllocation(
                name="main",
                title="Schematic",
                paper=pick_paper_size(len(components), total_pins),
                components=list(components),
                bypass_caps=all_bypass,
                straps=all_straps,
                sheet_annotations=_sheet_template_annotations(components),
            )
        ]

    # Larger designs: group by category
    sheets_map = {}  # sheet_name -> list of ComponentDef
    for comp in components:
        sheet_name = classify_component(comp)
        if sheet_name not in sheets_map:
            sheets_map[sheet_name] = []
        sheets_map[sheet_name].append(comp)

    # Build SheetAllocation objects
    result = []
    for sheet_name, comps in sheets_map.items():
        total_pins = sum(len(c.pins) for c in comps)
        all_bypass = []
        all_straps = []
        for c in comps:
            all_bypass.extend(c.bypass_caps)
            all_straps.extend(c.straps)

        result.append(
            SheetAllocation(
                name=sheet_name,
                title=SHEET_TITLES.get(sheet_name, sheet_name.title()),
                paper=pick_paper_size(len(comps), total_pins),
                components=comps,
                bypass_caps=all_bypass,
                straps=all_straps,
                sheet_annotations=_sheet_template_annotations(comps),
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
