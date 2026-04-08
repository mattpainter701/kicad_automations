"""Component database — stores IC definitions, pin maps, bypass/strap requirements.

Each component definition contains everything needed to place and wire it
in a schematic: pins, power requirements, bypass caps, strap resistors.
Keyed by MPN (manufacturer part number).
"""

import re
from dataclasses import dataclass, field

SUPPORT_PASSIVE_PRESENTATIONS = {"inherit", "literal_local", "symbolic", "topology_local"}
_ROLE_RE = re.compile(r"^[a-z][a-z0-9_]*$")
_GENERIC_PURPOSE_BY_CATEGORY = {
    "power": "Power conversion and rail conditioning",
    "transceiver": "RF conversion and high-speed signal processing",
    "fpga": "Programmable processing and high-speed digital interfacing",
    "clock": "Clock generation, cleanup, and distribution",
    "usb": "USB interface control and protocol bridging",
    "ethernet": "Ethernet / PoE interface and physical-layer control",
    "storage": "Boot and nonvolatile storage",
    "connector": "External interface and field connectivity",
    "debug": "Bring-up, test, and service access",
    "sensor": "Measurement and sensing interface",
}


def normalize_support_passive_presentation(value: str | None, default: str = "literal_local") -> str:
    """Return a validated support-passive presentation mode."""
    normalized = (value or default or "literal_local").strip().lower()
    if normalized not in SUPPORT_PASSIVE_PRESENTATIONS:
        valid = ", ".join(sorted(SUPPORT_PASSIVE_PRESENTATIONS))
        raise ValueError(f"Unknown support passive presentation '{value}'. Expected one of: {valid}")
    if normalized == "inherit":
        return normalize_support_passive_presentation(default, default="literal_local")
    return normalized


@dataclass(frozen=True)
class PresentationWiringPolicy:
    """Engine-level presentation defaults for generated schematic connectivity."""

    support_passives: str = "literal_local"

    def normalized(self) -> "PresentationWiringPolicy":
        return PresentationWiringPolicy(support_passives=normalize_support_passive_presentation(self.support_passives))


def normalize_presentation_wiring_policy(
    policy: PresentationWiringPolicy | dict | None,
) -> PresentationWiringPolicy:
    """Return a normalized presentation wiring policy from user/config input."""
    if policy is None:
        return PresentationWiringPolicy().normalized()
    if isinstance(policy, PresentationWiringPolicy):
        return policy.normalized()
    if isinstance(policy, dict):
        return PresentationWiringPolicy(
            support_passives=str(policy.get("support_passives", "literal_local"))
        ).normalized()
    raise TypeError(f"Unsupported presentation wiring policy type: {type(policy)!r}")


@dataclass
class PinDef:
    """A single pin on a component."""

    number: str  # "1", "2", "A3", "EP"
    name: str  # "VIN", "GND", "GPIO0"
    electrical_type: str  # input, output, bidirectional, passive, power_in, power_out
    side: str  # L, R, T, B — which side of the symbol box

    def as_tuple(self):
        return (self.number, self.name, self.electrical_type, self.side)


@dataclass
class BypassCap:
    """A bypass/decoupling capacitor required by an IC."""

    pin: str  # pin number or power net name this cap bypasses
    net: str  # power net (e.g. "VDD_3P3")
    gnd_net: str  # ground net (e.g. "GND")
    value: str  # "100nF", "10uF"
    footprint: str  # e.g. FP_0402C
    role: str = "decoupling"
    presentation: str = "topology_local"

    def __post_init__(self) -> None:
        if self.role and not _ROLE_RE.match(self.role):
            raise ValueError(f"Invalid BypassCap role: {self.role!r} (must be lowercase identifier)")


@dataclass
class StrapConfig:
    """A pull-up or pull-down strap resistor."""

    pin: str  # pin number
    net: str  # signal net name
    rail: str  # pull to this rail ("VDD_3P3" or "GND")
    value: str  # "10k", "4.7k"
    footprint: str
    role: str = "strap"
    presentation: str = "topology_local"

    def __post_init__(self) -> None:
        if self.role and not _ROLE_RE.match(self.role):
            raise ValueError(f"Invalid StrapConfig role: {self.role!r} (must be lowercase identifier)")


@dataclass
class PowerReq:
    """A power rail required by a component."""

    net: str  # "VDD_3P3", "VCCINT"
    voltage: float  # 3.3, 1.0
    max_current_ma: float = 0  # peak current draw


@dataclass
class ComponentDef:
    """Complete definition of a component for schematic generation.

    Contains everything needed to:
    1. Create the KiCad symbol (pins)
    2. Place it on the correct sheet (category)
    3. Wire it correctly (pin_nets)
    4. Generate supporting passives (bypass_caps, straps)
    """

    mpn: str  # "ESP32-WROOM-32E"
    ref_prefix: str = "U"  # "U", "J", "D", "R", "C", "L"
    value: str = ""  # display value
    footprint: str = ""  # KiCad footprint string
    description: str = ""
    category: str = "digital"  # power, digital, rf, connector, sensor, storage, debug, passive
    source_ref: str = ""  # BOM/design source reference for this specific instance
    source_mpn: str = ""  # original BOM MPN before registry aliasing
    source_value: str = ""  # original BOM value/comment field
    source_description: str = ""  # original BOM description
    source_manufacturer: str = ""  # original BOM manufacturer
    lcsc_pn: str = ""  # LCSC part number (e.g. "C14663") for JLCPCB assembly
    digikey_pn: str = ""  # DigiKey part number for prototype ordering
    features: list[str] = field(default_factory=list)  # optional feature summary tokens
    annotations: list[str] = field(default_factory=list)  # design rationale text near IC
    template_annotations: list[str] = field(default_factory=list)  # sheet-level notes from a template
    template_boundary_ports: list = field(default_factory=list)  # BoundaryPort-like objects from template
    template_local_wires: list = field(default_factory=list)  # LocalWire-like objects from template
    presentation_group: str = ""  # optional review-sheet partition grouping
    presentation_wiring_policy: PresentationWiringPolicy | None = None  # optional component-level rendering override

    pins: list[PinDef] = field(default_factory=list)
    pin_nets: dict = field(default_factory=dict)  # {pin_num: net_name} — signal connections
    power_pins: dict = field(default_factory=dict)  # {pin_num: power_net} — power connections

    power_reqs: list[PowerReq] = field(default_factory=list)
    bypass_caps: list[BypassCap] = field(default_factory=list)
    straps: list[StrapConfig] = field(default_factory=list)

    # Pin numbers intentionally left unconnected (no-connect by design).
    # The generator will place NC markers on these pins without warnings.
    # Pins NOT in this set and not in pin_nets/power_pins are flagged
    # according to their electrical type (error for power_in, warning for input).
    explicit_no_connects: set = field(default_factory=set)

    # For BGA ICs: callable that returns {ball: net} mapping
    pin_map_builder: object = None

    # Pre-built KiCad symbol S-expression (for custom library symbols).
    # When set, the engine embeds this instead of generating a generic box symbol.
    lib_symbol_sexpr: str = ""

    # Pinout provenance — used by the validator to gate schematic output.
    # "explicit"      — pin_map supplied in YAML spec or from KiCad library (trusted)
    # "kicad_library" — symbol resolved from installed KiCad symbol library (trusted)
    # "stub"          — generated from distributor package data only; pin assignments
    #                   are 1=pin1 … N=pinN placeholders and MUST NOT be routed.
    pinout_source: str = "explicit"

    # Set to True in YAML (pinout_verified: true) to acknowledge a stub pinout
    # has been manually confirmed against the datasheet.  Suppresses the
    # unverified-pinout validator error without requiring a full pin_map entry.
    pinout_verified: bool = False

    def pin_tuples(self):
        """Return pins as list of (number, name, type, side) tuples for create_generic_symbol."""
        return [p.as_tuple() for p in self.pins]

    def all_signal_nets(self):
        """All signal net names this component connects to."""
        return set(self.pin_nets.values())

    def all_power_nets(self):
        """All power net names this component needs."""
        return set(self.power_pins.values()) | {r.net for r in self.power_reqs}

    def prefer_multi_column_symbol(self) -> bool:
        """Whether this component should use a multi-column generic symbol.

        Dense left/right-only symbols benefit from review-oriented generic
        rendering once a single face becomes tall enough to read as a label
        wall. This is intentionally broader than the original >100-pin BGA
        case so medium-large imported memory/interface symbols can still use
        the generic multi-column path.
        """
        if any(pin.side in ("T", "B") for pin in self.pins):
            return False

        return self.preferred_symbol_column_segments() is not None

    def preferred_symbol_column_segments(self) -> int | None:
        """Preferred review-time generic symbol columns for dense L/R symbols."""
        if any(pin.side in ("T", "B") for pin in self.pins):
            return None

        max_side = max(
            sum(1 for pin in self.pins if pin.side == "L"),
            sum(1 for pin in self.pins if pin.side == "R"),
        )
        if max_side < 44:
            return None

        if max_side >= 180:
            return 4
        if max_side >= 100:
            return 3
        return 2

    def preferred_symbol_pin_pitch_mm(self) -> float | None:
        """Preferred review-time pin pitch for readability-sensitive symbols."""
        max_side = max(
            [
                sum(1 for pin in self.pins if pin.side == "L"),
                sum(1 for pin in self.pins if pin.side == "R"),
                sum(1 for pin in self.pins if pin.side == "T"),
                sum(1 for pin in self.pins if pin.side == "B"),
            ],
            default=0,
        )
        max_name_len = max((len(pin.name or "") for pin in self.pins), default=0)
        columns = self.preferred_symbol_column_segments() or 1

        if columns > 1 and max_side >= 20:
            return 5.08

        if columns == 1 and self.category in {"usb", "power", "fpga"} and max_side >= 3 and max_name_len >= 10:
            return 5.08

        return None


def _compact_text(text: str, limit: int = 88) -> str:
    text = " ".join((text or "").split())
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)].rstrip() + "..."


def component_purpose_summary(comp: ComponentDef) -> str:
    """Return a short reader-facing purpose summary for a component."""
    desc = " ".join(
        part
        for part in (
            comp.source_description,
            comp.description,
        )
        if part
    ).strip()
    desc_l = desc.lower()

    keyword_purposes = (
        (("usb pd", "type-c pd", "sink controller"), "USB-C power negotiation and sink control"),
        (("buck", "sync buck", "regulator"), "Power rail generation and voltage regulation"),
        (("ldo", "low-noise"), "Quiet local rail regulation and analog supply cleanup"),
        (("clock", "pll", "sysref", "jesd"), "Clock synthesis, cleanup, and timing distribution"),
        (("rf transceiver", "2t2r", "6ghz"), "RF transceiver front end and sample-data interface"),
        (("zynq", "arm", "fpga"), "Application processing, FPGA logic, and system control"),
        (("ddr3", "sdram"), "Working memory for the processing subsystem"),
        (("usb 3", "superspeed", "fx3"), "USB data bridge and host interface control"),
        (("usb 2", "hub"), "USB fanout and downstream-port management"),
        (("ethernet", "rgmii", "phy"), "Ethernet physical-layer interface"),
        (("poe",), "Power-over-Ethernet input and front-end conversion"),
        (("flash", "qspi", "nor"), "Boot image storage and nonvolatile configuration"),
        (("mux", "switch"), "Signal path selection and interface switching"),
    )
    for keywords, purpose in keyword_purposes:
        if any(keyword in desc_l for keyword in keywords):
            return purpose

    if desc:
        return _compact_text(desc, 72)
    return _GENERIC_PURPOSE_BY_CATEGORY.get(comp.category, "Functional support within the design")


def component_needs_explanation(comp: ComponentDef) -> bool:
    """Return True when the component should get a review explanation block."""
    if comp.ref_prefix == "U":
        return True
    return comp.category in {"power", "clock", "transceiver", "fpga", "usb", "ethernet", "storage"}


def component_explanation_lines(comp: ComponentDef, ref: str = "") -> list[str]:
    """Return a compact explanation block for schematic review output."""
    if not component_needs_explanation(comp):
        return []

    display_name = comp.source_mpn or comp.value or comp.mpn
    heading_prefix = f"{ref} " if ref else ""
    heading = _compact_text(
        f"{heading_prefix}{display_name}: {component_purpose_summary(comp)}",
        92,
    )

    lines = [heading]
    detail_lines = [_compact_text(line, 92) for line in comp.annotations if line.strip()]

    if not detail_lines:
        fallback: list[str] = []
        if comp.description:
            fallback.append(_compact_text(comp.description, 92))
        if comp.power_reqs:
            rails = ", ".join(sorted({req.net for req in comp.power_reqs if req.net}))
            if rails:
                fallback.append(_compact_text(f"Primary rails: {rails}", 92))
        elif comp.power_pins:
            rails = ", ".join(sorted({net for net in comp.power_pins.values() if net}))
            if rails:
                fallback.append(_compact_text(f"Key rails: {rails}", 92))
        if comp.pin_nets:
            named_nets = sorted({net for net in comp.pin_nets.values() if net})[:4]
            if named_nets:
                fallback.append(_compact_text(f"Interfaces: {', '.join(named_nets)}", 92))
        detail_lines = fallback

    for line in detail_lines[:3]:
        if line and line != heading:
            lines.append(f"- {line}")

    return lines


class ComponentRegistry:
    """Registry of known components, queryable by MPN."""

    def __init__(self):
        self._components = {}  # mpn -> ComponentDef
        self._aliases = {}  # alias_mpn -> canonical_mpn

    def register(self, comp: ComponentDef):
        self._components[comp.mpn] = comp

    def add_alias(self, alias: str, canonical: str):
        """Map an alias MPN to a canonical MPN (e.g. BOM suffix variants)."""
        self._aliases[alias] = canonical

    def get(self, mpn: str) -> ComponentDef | None:
        import re as _re

        comp = self._components.get(mpn)
        if comp:
            return comp
        canonical = self._aliases.get(mpn)
        if canonical:
            return self._components.get(canonical)
        stripped = _re.sub(r"[-/:](?:7|ND|P|TR|REEL7?|NOPB|CT)$", "", mpn)
        if stripped != mpn:
            return self._components.get(stripped)
        return None

    def find_by_category(self, category: str) -> list[ComponentDef]:
        return [c for c in self._components.values() if c.category == category]

    def all_mpns(self):
        return list(self._components.keys())

    def __len__(self):
        return len(self._components)

    def load_json(self, path: str) -> int:
        """Load component definitions from a JSON file.

        The file should contain a list of objects, each with at least ``mpn``
        and ``pins`` fields matching the :class:`ComponentDef` schema.  Returns
        the number of components loaded.

        Example JSON::

            [
              {
                "mpn": "MY_IC",
                "ref_prefix": "U",
                "value": "MY_IC",
                "footprint": "Package_SO:SOIC-8_3.9x4.9mm_P1.27mm",
                "description": "Custom IC",
                "category": "analog",
                "pins": [
                  {"number": "1", "name": "IN", "electrical_type": "input", "side": "L"},
                  {"number": "2", "name": "GND", "electrical_type": "power_in", "side": "B"}
                ],
                "power_pins": {"2": "GND"},
                "bypass_caps": [
                  {"pin": "auto", "net": "VDD", "gnd_net": "GND", "value": "100nF",
                   "footprint": "Capacitor_SMD:C_0402_1005Metric"}
                ]
              }
            ]
        """
        import json
        from pathlib import Path

        data = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(data, list):
            data = [data]
        count = 0
        for entry in data:
            if not isinstance(entry, dict) or "mpn" not in entry:
                continue
            pins = [
                PinDef(
                    number=str(p.get("number", "")),
                    name=str(p.get("name", "~")),
                    electrical_type=str(p.get("electrical_type", "passive")),
                    side=str(p.get("side", "L")),
                )
                for p in entry.get("pins", [])
            ]
            caps = [
                BypassCap(
                    pin=str(c.get("pin", "auto")),
                    net=str(c.get("net", "")),
                    gnd_net=str(c.get("gnd_net", "GND")),
                    value=str(c.get("value", "100nF")),
                    footprint=str(c.get("footprint", "Capacitor_SMD:C_0402_1005Metric")),
                    role=str(c.get("role", "decoupling")),
                    presentation=str(c.get("presentation", "topology_local")),
                )
                for c in entry.get("bypass_caps", [])
            ]
            straps = [
                StrapConfig(
                    pin=str(s.get("pin", "")),
                    net=str(s.get("net", "")),
                    rail=str(s.get("rail", "GND")),
                    value=str(s.get("value", "10k")),
                    footprint=str(s.get("footprint", "Resistor_SMD:R_0402_1005Metric")),
                    role=str(s.get("role", "strap")),
                    presentation=str(s.get("presentation", "topology_local")),
                )
                for s in entry.get("straps", [])
            ]
            comp = ComponentDef(
                mpn=str(entry["mpn"]),
                ref_prefix=str(entry.get("ref_prefix", "U")),
                value=str(entry.get("value", entry["mpn"])),
                footprint=str(entry.get("footprint", "")),
                description=str(entry.get("description", "")),
                category=str(entry.get("category", "digital")),
                pins=pins,
                pin_nets={str(k): str(v) for k, v in entry.get("pin_nets", {}).items()},
                power_pins={str(k): str(v) for k, v in entry.get("power_pins", {}).items()},
                bypass_caps=caps,
                straps=straps,
            )
            self.register(comp)
            count += 1
        return count

    def load_json_dir(self, directory: str) -> int:
        """Load all ``*.json`` component files from a directory."""
        from pathlib import Path

        total = 0
        d = Path(directory)
        if not d.is_dir():
            return 0
        for f in sorted(d.glob("*.json")):
            total += self.load_json(str(f))
        return total


@dataclass
class BomRow:
    """A single parsed BOM line item."""

    ref: str  # "U1", "C3", "R7"
    mpn: str = ""  # manufacturer part number
    value: str = ""  # "100nF", "10k", "ESP32-WROOM-32E"
    footprint: str = ""  # KiCad footprint string
    description: str = ""
    quantity: int = 1
    manufacturer: str = ""
    supplier_pn: str = ""  # DigiKey/LCSC/Mouser PN


# Column name aliases for auto-detection (lowercase → canonical)
_COLUMN_ALIASES = {
    # Reference
    "reference": "ref",
    "ref": "ref",
    "designator": "ref",
    "refdes": "ref",
    "ref des": "ref",
    "part reference": "ref",
    # MPN
    "mpn": "mpn",
    "part number": "mpn",
    "part": "mpn",
    "mfg part": "mpn",
    "manufacturer part": "mpn",
    "mfr. part #": "mpn",
    "mfg part #": "mpn",
    "manufacturer part number": "mpn",
    "mfg p/n": "mpn",
    # Value
    "value": "value",
    "val": "value",
    "comment": "value",
    # Footprint
    "footprint": "footprint",
    "package": "footprint",
    "case/package": "footprint",
    "case": "footprint",
    "pcb footprint": "footprint",
    # Description
    "description": "description",
    "desc": "description",
    "part description": "description",
    # Quantity
    "quantity": "quantity",
    "qty": "quantity",
    "qty.": "quantity",
    "count": "quantity",
    "qty_sdr": "quantity",
    "qty_mini": "quantity",
    # Manufacturer
    "manufacturer": "manufacturer",
    "mfg": "manufacturer",
    "mfr": "manufacturer",
    "mfr.": "manufacturer",
    # Supplier PN
    "digikey_pn": "supplier_pn",
    "digi-key part number": "supplier_pn",
    "lcsc_pn": "supplier_pn",
    "lcsc part": "supplier_pn",
    "lcsc part #": "supplier_pn",
    "mouser_pn": "supplier_pn",
    "mouser part number": "supplier_pn",
    "supplier part number": "supplier_pn",
    # LCSC-specific
    "mfr part": "mpn",
    "mfr part #": "mpn",
    "mfr. part": "mpn",
}


def _detect_delimiter(first_line: str) -> str:
    """Auto-detect CSV delimiter (comma, tab, semicolon, pipe)."""
    counts = {
        ",": first_line.count(","),
        "\t": first_line.count("\t"),
        ";": first_line.count(";"),
        "|": first_line.count("|"),
    }
    return max(counts, key=counts.get) if max(counts.values()) > 0 else ","


def _normalize_columns(header_row: list[str]) -> dict[int, str]:
    """Map column indices to canonical field names."""
    mapping = {}
    for i, col in enumerate(header_row):
        # Aggressively normalize: lowercase, strip whitespace, #, trailing .
        normalized = col.strip().lower().rstrip("#").rstrip(".").rstrip("#").strip()
        canonical = _COLUMN_ALIASES.get(normalized)
        # Also try with trailing # and . included (some aliases have them)
        if not canonical:
            canonical = _COLUMN_ALIASES.get(col.strip().lower())
        if canonical and canonical not in mapping.values():
            mapping[i] = canonical
    return mapping


def _expand_ref_range(token: str) -> list[str]:
    """Expand a single reference token, including simple numeric ranges.

    Examples:
    - R1-R4 -> [R1, R2, R3, R4]
    - C10..C12 -> [C10, C11, C12]
    """
    t = (token or "").strip()
    if not t:
        return []

    # prefix + start + ("-" or "..") + optional prefix + end
    m = re.fullmatch(r"([A-Za-z]+)(\d+)\s*(?:-|\.\.)\s*([A-Za-z]+)?(\d+)", t)
    if not m:
        return [t]

    p1, start_s, p2, end_s = m.groups()
    p2 = p2 or p1
    if p1.upper() != p2.upper():
        return [t]

    start = int(start_s)
    end = int(end_s)
    step = 1 if end >= start else -1
    width = max(len(start_s), len(end_s))
    return [f"{p1}{i:0{width}d}" for i in range(start, end + step, step)]


def _split_refs(ref_field: str) -> list[str]:
    """Split a BOM ref field into individual designators.

    Handles common delimiters like commas/semicolons/whitespace.
    """
    raw = (ref_field or "").strip()
    if not raw:
        return []
    parts = re.split(r"[,\s;]+", raw)
    out = []
    for part in (p.strip() for p in parts if p.strip()):
        out.extend(_expand_ref_range(part))
    return out


def _parse_quantity(qty_str: str) -> tuple[int, bool]:
    """Parse BOM quantity variants like '3', '3.0', '3x', 'x3', '1,000'.

    Returns: (qty, parsed_ok)
    """
    raw = (qty_str or "").strip().lower().replace(",", "")
    if not raw:
        return 1, True

    # Common suffix/prefix notation from distributor exports.
    raw = raw.removesuffix("x").removeprefix("x").strip()

    try:
        qty = int(float(raw))
        return (qty if qty > 0 else 1), True
    except ValueError:
        return 1, False


def parse_bom_csv(csv_path: str) -> list[BomRow]:
    """Parse a BOM CSV/TSV file with auto-detected format.

    Handles:
    - project BOM CSV
    - KiCad BOM export (Reference, Value, Footprint, ...)
    - DigiKey cart export (Digi-Key Part Number, Manufacturer Part Number, ...)
    - LCSC BOM (LCSC Part #, MFR. Part #, Package, ...)
    - Generic CSV/TSV with common column names

    Auto-detects: delimiter (comma/tab/semicolon/pipe), column mapping,
    encoding (UTF-8 with optional BOM).
    """
    import csv
    from pathlib import Path

    path = Path(csv_path)
    if not path.exists():
        raise FileNotFoundError(f"BOM file not found: {csv_path}")

    # Read with BOM-aware encoding
    raw = path.read_bytes()
    if raw.startswith(b"\xef\xbb\xbf"):
        text = raw.decode("utf-8-sig")
    else:
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            text = raw.decode("latin-1")

    lines = text.splitlines()
    if not lines:
        return []

    # Skip blank/comment lines at the top
    header_idx = 0
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and not stripped.startswith("//"):
            header_idx = i
            break

    # Detect delimiter
    delimiter = _detect_delimiter(lines[header_idx])

    # Parse header
    reader = csv.reader([lines[header_idx]], delimiter=delimiter)
    header = next(reader)
    col_map = _normalize_columns(header)

    has_ref_column = "ref" in col_map.values()
    if not has_ref_column:
        print("WARNING: BOM has no reference/designator column; using quantity-only expansion mode.")

    # Parse data rows
    rows = []
    data_reader = csv.reader(lines[header_idx + 1 :], delimiter=delimiter)
    for csv_row in data_reader:
        if not csv_row or not any(c.strip() for c in csv_row):
            continue

        # Map columns to fields
        fields = {}
        for col_idx, field_name in col_map.items():
            if col_idx < len(csv_row):
                fields[field_name] = csv_row[col_idx].strip()

        ref = fields.get("ref", "")
        mpn = fields.get("mpn", "")
        value = fields.get("value", "")

        # Skip empty rows
        if not ref and not mpn and not value:
            continue

        # If no MPN, try to use value as MPN (common for KiCad BOMs)
        if not mpn and value:
            mpn = value

        qty_raw = fields.get("quantity", "1")
        qty, qty_ok = _parse_quantity(qty_raw)
        if not qty_ok:
            print(f"WARNING: Could not parse quantity '{qty_raw}' for row ref='{ref}' mpn='{mpn}'; defaulting to 1.")

        refs = _split_refs(ref) if has_ref_column else []

        # If refs are explicitly listed (e.g. "R1,R2,R3"), expand to one row per ref.
        # For a single explicit ref, preserve quantity from the BOM line.
        if len(refs) > 1:
            if qty > 1 and qty != len(refs):
                print(
                    f"WARNING: Ref/Qty mismatch for '{ref}': {len(refs)} refs vs qty={qty}; "
                    "expanding by refs and ignoring qty."
                )
            for ref_item in refs:
                rows.append(
                    BomRow(
                        ref=ref_item,
                        mpn=mpn,
                        value=value,
                        footprint=fields.get("footprint", ""),
                        description=fields.get("description", ""),
                        quantity=1,
                        manufacturer=fields.get("manufacturer", ""),
                        supplier_pn=fields.get("supplier_pn", ""),
                    )
                )
            continue
        elif len(refs) == 1:
            ref = refs[0]
            if qty > 1 and ref:
                print(f"WARNING: Row '{ref}' has quantity={qty} but only 1 ref. Expanding to {qty} instances.")

        rows.append(
            BomRow(
                ref=ref,
                mpn=mpn,
                value=value,
                footprint=fields.get("footprint", ""),
                description=fields.get("description", ""),
                quantity=qty,
                manufacturer=fields.get("manufacturer", ""),
                supplier_pn=fields.get("supplier_pn", ""),
            )
        )

    return rows


# ================================================================
# Generic passive component generator
# ================================================================

# Footprint inference from value string
_PASSIVE_FOOTPRINT_MAP = {
    "0201": {"C": "Capacitor_SMD:C_0201_0603Metric", "R": "Resistor_SMD:R_0201_0603Metric"},
    "0402": {"C": "Capacitor_SMD:C_0402_1005Metric", "R": "Resistor_SMD:R_0402_1005Metric"},
    "0603": {"C": "Capacitor_SMD:C_0603_1608Metric", "R": "Resistor_SMD:R_0603_1608Metric"},
    "0805": {
        "C": "Capacitor_SMD:C_0805_2012Metric",
        "R": "Resistor_SMD:R_0805_2012Metric",
        "L": "Inductor_SMD:L_0805_2012Metric",
    },
    "1206": {"C": "Capacitor_SMD:C_1206_3216Metric", "R": "Resistor_SMD:R_1206_3216Metric"},
}


def _infer_passive_type(ref: str, value: str, footprint: str) -> str | None:
    """Infer passive type code ("C", "R", "L") from ref/value/footprint."""
    prefix = ""
    for ch in ref:
        if ch.isalpha():
            prefix += ch
        else:
            break
    prefix = prefix.upper()
    if prefix in ("C", "R", "L", "FB"):
        return prefix

    fp = (footprint or "").lower()
    if "resistor" in fp:
        return "R"
    if "capacitor" in fp:
        return "C"
    if "inductor" in fp:
        return "L"

    v = (value or "").strip().lower().replace(" ", "")
    if not v:
        return None

    # Common resistor notations: 10k, 4.7R, 1M, 100 ohm
    if "ohm" in v or re.fullmatch(r"\d+([.,]\d+)?[rkm]([ωΩ]|ohm)?", v):
        return "R"

    # IEC resistor notation: 4K7, 2M2, 0R0
    if re.fullmatch(r"\d+[rkm]\d+", v):
        return "R"

    # Common capacitor notations: 100nF, 10uF, 47pF
    if re.fullmatch(r"\d+([.,]\d+)?[pnum]?f", v):
        return "C"

    # Common inductor notations: 4.7uH, 10mH, 220nH
    if re.fullmatch(r"\d+([.,]\d+)?[num]?h", v):
        return "L"

    return None


def infer_passive_component(ref: str, value: str, footprint: str = "") -> ComponentDef | None:
    """Auto-generate a ComponentDef for a passive component from ref + value.

    Handles: C1=100nF, R3=10k, L1=4.7uH, etc.
    Infers footprint from value or footprint string if provided.
    """
    prefix = _infer_passive_type(ref, value, footprint)
    if prefix is None:
        return None

    sym_type = "L" if prefix == "FB" else prefix  # Ferrite beads use inductor symbol
    category = "passive"

    # Infer footprint
    if not footprint:
        # Try to detect package size from value or ref
        # Default to 0402 for C/R, 0805 for L
        pkg = "0402" if sym_type in ("C", "R") else "0805"

        # Check if value mentions a package size
        for size in ("0201", "0402", "0603", "0805", "1206", "1210"):
            if size in value or size in ref:
                pkg = size
                break

        footprint = _PASSIVE_FOOTPRINT_MAP.get(pkg, {}).get(sym_type, "")

    sym_name = {"C": "C_Small", "R": "R_Small", "L": "L_Small"}[sym_type]

    return ComponentDef(
        mpn=f"{sym_name}_{value}",
        ref_prefix=prefix,
        value=value,
        footprint=footprint,
        description=f"Passive {sym_type} {value}",
        category=category,
        pins=[
            PinDef("1", "~", "passive", "L"),
            PinDef("2", "~", "passive", "R"),
        ],
    )


# ================================================================
# Auto-decoupling for ICs with power pins but no explicit bypass caps
# ================================================================

# Default footprints for auto-generated bypass caps
_AUTO_BYPASS_FP_HF = "Capacitor_SMD:C_0402_1005Metric"
_AUTO_BYPASS_FP_BULK = "Capacitor_SMD:C_0805_2012Metric"

# Power nets that are ground (not decoupled, used as gnd_net)
_GROUND_NETS = frozenset({"GND", "AGND", "DGND", "GNDA", "GNDD", "VSS", "VSSA"})

# Minimum pin count for an IC to get auto-decoupling (skip simple passives/connectors)
_AUTO_BYPASS_MIN_PINS = 6


def auto_generate_bypass_caps(components: list[ComponentDef]) -> int:
    """Add basic decoupling caps to ICs that have power pins but no explicit bypass_caps.

    For each IC with >= _AUTO_BYPASS_MIN_PINS pins and at least one non-ground power pin:
    - Adds one 100nF HF cap per unique power net
    - Adds one 10uF bulk cap if there are >= 3 unique power nets

    Returns the number of components that received auto-generated bypass caps.
    This is a generic engine behavior, not project-specific.
    """
    count = 0
    _power_categories = {"power", "regulator", "poe"}
    for comp in components:
        if comp.bypass_caps:
            continue  # already has explicit bypass caps
        if not comp.power_pins:
            continue  # no power pins assigned
        # Power ICs (regulators, etc.) always get decoupling regardless of pin count.
        # Other ICs need at least _AUTO_BYPASS_MIN_PINS to avoid decoupling bare passives/connectors.
        is_power_ic = comp.category in _power_categories or comp.ref_prefix == "U"
        if not is_power_ic and len(comp.pins) < _AUTO_BYPASS_MIN_PINS:
            continue

        # Collect unique non-ground power nets
        power_nets = set()
        gnd_net = "GND"  # default
        for pin_num, net in comp.power_pins.items():
            if net in _GROUND_NETS:
                gnd_net = net
            else:
                power_nets.add(net)

        if not power_nets:
            continue

        # Generate one 100nF HF cap per unique power net
        for net in sorted(power_nets):
            comp.bypass_caps.append(
                BypassCap(
                    pin="auto",
                    net=net,
                    gnd_net=gnd_net,
                    value="100nF",
                    footprint=_AUTO_BYPASS_FP_HF,
                )
            )

        # Add one 10uF bulk cap if many power domains
        if len(power_nets) >= 3:
            # Bulk cap on the highest-voltage rail (heuristic: longest net name with "3P3" or "5V")
            main_rail = sorted(power_nets, key=lambda n: ("5V" in n, "3P3" in n, n), reverse=True)[0]
            comp.bypass_caps.append(
                BypassCap(
                    pin="auto",
                    net=main_rail,
                    gnd_net=gnd_net,
                    value="10uF",
                    footprint=_AUTO_BYPASS_FP_BULK,
                )
            )

        count += 1
    return count


# ================================================================
# Built-in component library — common parts for proof-of-concept
# ================================================================
def _builtin_components():
    """Return a registry pre-loaded with common components."""
    reg = ComponentRegistry()

    # --- AMS1117-3.3 LDO (SOT-223) ---
    reg.register(
        ComponentDef(
            mpn="AMS1117-3.3",
            ref_prefix="U",
            value="AMS1117-3.3",
            footprint="Package_TO_SOT_SMD:SOT-223-3_TabPin2",
            description="3.3V 1A LDO Regulator",
            category="power",
            pins=[
                PinDef("1", "GND", "power_in", "B"),
                PinDef("2", "VOUT", "power_out", "R"),
                PinDef("3", "VIN", "power_in", "L"),
            ],
            pin_nets={},
            power_pins={"1": "GND", "2": "VDD_3P3", "3": "VIN"},
            power_reqs=[PowerReq("VIN", 5.0, 1000)],
            bypass_caps=[
                BypassCap("3", "VIN", "GND", "10uF", "Capacitor_SMD:C_0805_2012Metric"),
                BypassCap("2", "VDD_3P3", "GND", "10uF", "Capacitor_SMD:C_0805_2012Metric"),
                BypassCap("2", "VDD_3P3", "GND", "100nF", "Capacitor_SMD:C_0402_1005Metric"),
            ],
        )
    )

    # --- ESP32-WROOM-32E Module (38-pin) ---
    esp_pins = [
        PinDef("1", "GND", "power_in", "B"),
        PinDef("2", "3V3", "power_in", "T"),
        PinDef("3", "EN", "input", "L"),
        PinDef("4", "SENSOR_VP", "input", "L"),
        PinDef("5", "SENSOR_VN", "input", "L"),
        PinDef("6", "IO34", "input", "L"),
        PinDef("7", "IO35", "input", "L"),
        PinDef("8", "IO32", "bidirectional", "L"),
        PinDef("9", "IO33", "bidirectional", "L"),
        PinDef("10", "IO25", "bidirectional", "L"),
        PinDef("11", "IO26", "bidirectional", "L"),
        PinDef("12", "IO27", "bidirectional", "L"),
        PinDef("13", "IO14", "bidirectional", "R"),
        PinDef("14", "IO12", "bidirectional", "R"),
        PinDef("15", "GND2", "power_in", "B"),
        PinDef("16", "IO13", "bidirectional", "R"),
        PinDef("17", "SD2", "bidirectional", "R"),
        PinDef("18", "SD3", "bidirectional", "R"),
        PinDef("19", "CMD", "bidirectional", "R"),
        PinDef("20", "CLK", "output", "R"),
        PinDef("21", "SD0", "bidirectional", "R"),
        PinDef("22", "SD1", "bidirectional", "R"),
        PinDef("23", "IO15", "bidirectional", "R"),
        PinDef("24", "IO2", "bidirectional", "R"),
        PinDef("25", "IO0", "bidirectional", "L"),
        PinDef("26", "IO4", "bidirectional", "R"),
        PinDef("27", "IO16", "bidirectional", "R"),
        PinDef("28", "IO17", "bidirectional", "R"),
        PinDef("29", "IO5", "bidirectional", "R"),
        PinDef("30", "IO18", "bidirectional", "R"),
        PinDef("31", "IO19", "bidirectional", "R"),
        PinDef("32", "NC", "passive", "R"),
        PinDef("33", "IO21", "bidirectional", "R"),
        PinDef("34", "RXD0", "input", "L"),
        PinDef("35", "TXD0", "output", "L"),
        PinDef("36", "IO22", "bidirectional", "R"),
        PinDef("37", "IO23", "bidirectional", "R"),
        PinDef("38", "GND3", "power_in", "B"),
        PinDef("39", "GND_PAD", "power_in", "B"),
    ]
    reg.register(
        ComponentDef(
            mpn="ESP32-WROOM-32E",
            ref_prefix="U",
            value="ESP32-WROOM-32E",
            footprint="RF_Module:ESP32-WROOM-32E",
            description="WiFi+BT Module (ESP32, 4MB Flash)",
            category="digital",
            pins=esp_pins,
            pin_nets={
                "3": "ESP_EN",
                "25": "ESP_IO0",
                "34": "UART0_RX",
                "35": "UART0_TX",
            },
            power_pins={"1": "GND", "2": "VDD_3P3", "15": "GND", "38": "GND", "39": "GND"},
            power_reqs=[PowerReq("VDD_3P3", 3.3, 500)],
            bypass_caps=[
                BypassCap("2", "VDD_3P3", "GND", "10uF", "Capacitor_SMD:C_0805_2012Metric"),
                BypassCap("2", "VDD_3P3", "GND", "100nF", "Capacitor_SMD:C_0402_1005Metric"),
            ],
            straps=[
                StrapConfig("3", "ESP_EN", "VDD_3P3", "10k", "Resistor_SMD:R_0402_1005Metric"),
                StrapConfig("25", "ESP_IO0", "VDD_3P3", "10k", "Resistor_SMD:R_0402_1005Metric"),
            ],
        )
    )

    # --- USB-C power-only connector (4-pin simplified) ---
    reg.register(
        ComponentDef(
            mpn="USB-C-PWR",
            ref_prefix="J",
            value="USB-C",
            footprint="Connector_USB:USB_C_Receptacle_GCT_USB4085",
            description="USB-C Power Input",
            category="connector",
            pins=[
                PinDef("A4", "VBUS", "power_out", "R"),
                PinDef("A1", "GND", "power_in", "B"),
                PinDef("B4", "VBUS2", "passive", "R"),
                PinDef("B1", "GND2", "power_in", "B"),
                PinDef("A5", "CC1", "bidirectional", "L"),
                PinDef("B5", "CC2", "bidirectional", "L"),
            ],
            pin_nets={"A5": "USB_CC1", "B5": "USB_CC2"},
            power_pins={"A4": "VBUS_5V", "A1": "GND", "B4": "VBUS_5V", "B1": "GND"},
            straps=[
                StrapConfig(
                    "A5",
                    "USB_CC1",
                    "GND",
                    "5.1k",
                    "Resistor_SMD:R_0402_1005Metric",
                    role="termination",
                    presentation="topology_local",
                ),
                StrapConfig(
                    "B5",
                    "USB_CC2",
                    "GND",
                    "5.1k",
                    "Resistor_SMD:R_0402_1005Metric",
                    role="termination",
                    presentation="topology_local",
                ),
            ],
        )
    )

    # --- BME280 Environmental Sensor (LGA-8) ---
    reg.register(
        ComponentDef(
            mpn="BME280",
            ref_prefix="U",
            value="BME280",
            footprint="Package_LGA:Bosch_LGA-8_2.5x2.5mm",
            description="Temperature/Humidity/Pressure Sensor I2C/SPI",
            category="sensor",
            pins=[
                PinDef("1", "GND", "power_in", "B"),
                PinDef("2", "CSB", "input", "L"),
                PinDef("3", "SDI", "bidirectional", "L"),
                PinDef("4", "SCK", "input", "L"),
                PinDef("5", "SDO", "output", "R"),
                PinDef("6", "VDDIO", "power_in", "T"),
                PinDef("7", "GND2", "power_in", "B"),
                PinDef("8", "VDD", "power_in", "T"),
            ],
            pin_nets={"3": "I2C_SDA", "4": "I2C_SCL", "5": "BME_SDO"},
            power_pins={"1": "GND", "2": "VDD_3P3", "6": "VDD_3P3", "7": "GND", "8": "VDD_3P3"},
            power_reqs=[PowerReq("VDD_3P3", 3.3, 4)],
            bypass_caps=[
                BypassCap("8", "VDD_3P3", "GND", "100nF", "Capacitor_SMD:C_0402_1005Metric"),
            ],
        )
    )

    # --- W25Q128 SPI Flash (SOIC-8) ---
    reg.register(
        ComponentDef(
            mpn="W25Q128JVSIQ",
            ref_prefix="U",
            value="W25Q128JVSIQ",
            footprint="Package_SO:SOIC-8_5.23x5.23mm_P1.27mm",
            description="128Mb SPI NOR Flash",
            category="storage",
            pins=[
                PinDef("1", "CS", "input", "L"),
                PinDef("2", "DO", "output", "R"),
                PinDef("3", "WP", "input", "L"),
                PinDef("4", "GND", "power_in", "B"),
                PinDef("5", "DI", "input", "L"),
                PinDef("6", "CLK", "input", "L"),
                PinDef("7", "HOLD", "input", "R"),
                PinDef("8", "VCC", "power_in", "T"),
            ],
            pin_nets={"1": "FLASH_CS", "2": "SPI_MISO", "5": "SPI_MOSI", "6": "SPI_CLK"},
            power_pins={"3": "VDD_3P3", "4": "GND", "7": "VDD_3P3", "8": "VDD_3P3"},
            power_reqs=[PowerReq("VDD_3P3", 3.3, 50)],
            bypass_caps=[
                BypassCap("8", "VDD_3P3", "GND", "100nF", "Capacitor_SMD:C_0402_1005Metric"),
            ],
        )
    )

    # --- ATmega328P (TQFP-32 simplified) ---
    reg.register(
        ComponentDef(
            mpn="ATmega328P-AU",
            ref_prefix="U",
            value="ATmega328P",
            footprint="Package_QFP:TQFP-32_7x7mm_P0.8mm",
            description="8-bit AVR MCU, 32KB Flash",
            category="digital",
            pins=[
                PinDef("4", "VCC", "power_in", "T"),
                PinDef("5", "GND", "power_in", "B"),
                PinDef("6", "XTAL1", "input", "L"),
                PinDef("7", "XTAL2", "output", "L"),
                PinDef("29", "PC6/RESET", "input", "R"),
                PinDef("30", "PD0/RXD", "input", "R"),
                PinDef("31", "PD1/TXD", "output", "R"),
            ],
            pin_nets={"29": "RESET_N", "30": "UART_RX", "31": "UART_TX"},
            power_pins={"4": "VDD_5V", "5": "GND"},
            power_reqs=[PowerReq("VDD_5V", 5.0, 30)],
            bypass_caps=[BypassCap("4", "VDD_5V", "GND", "100nF", "Capacitor_SMD:C_0402_1005Metric")],
        )
    )

    # --- STM32F103C8T6 (LQFP-48 simplified) ---
    reg.register(
        ComponentDef(
            mpn="STM32F103C8T6",
            ref_prefix="U",
            value="STM32F103C8T6",
            footprint="Package_QFP:LQFP-48_7x7mm_P0.5mm",
            description="ARM Cortex-M3 MCU, 64KB Flash",
            category="digital",
            pins=[
                PinDef("24", "VSSA", "power_in", "B"),
                PinDef("23", "VDDA", "power_in", "T"),
                PinDef("35", "VSS_1", "power_in", "B"),
                PinDef("36", "VDD_1", "power_in", "T"),
                PinDef("7", "BOOT0", "input", "L"),
                PinDef("44", "NRST", "input", "R"),
                PinDef("37", "PA13/SWDIO", "bidirectional", "R"),
                PinDef("34", "PA14/SWCLK", "input", "R"),
            ],
            pin_nets={"7": "BOOT0", "44": "RESET_N", "37": "SWDIO", "34": "SWCLK"},
            power_pins={"23": "VDD_3P3", "24": "GND", "35": "GND", "36": "VDD_3P3"},
            power_reqs=[PowerReq("VDD_3P3", 3.3, 80)],
            bypass_caps=[BypassCap("36", "VDD_3P3", "GND", "100nF", "Capacitor_SMD:C_0402_1005Metric")],
        )
    )

    # --- RP2040 (QFN-56 simplified) ---
    reg.register(
        ComponentDef(
            mpn="RP2040",
            ref_prefix="U",
            value="RP2040",
            footprint="Package_DFN_QFN:QFN-56-1EP_7x7mm_P0.4mm_EP3.2x3.2mm",
            description="Dual-core Cortex-M0+ MCU",
            category="digital",
            pins=[
                PinDef("49", "RUN", "input", "L"),
                PinDef("46", "SWCLK", "input", "R"),
                PinDef("47", "SWD", "bidirectional", "R"),
                PinDef("44", "USB_DP", "bidirectional", "L"),
                PinDef("45", "USB_DM", "bidirectional", "L"),
                PinDef("50", "ADC_AVDD", "power_in", "T"),
                PinDef("53", "IOVDD", "power_in", "T"),
                PinDef("57", "DVDD", "power_in", "T"),
                PinDef("33", "GND", "power_in", "B"),
            ],
            pin_nets={
                "49": "RESET_N",
                "46": "SWCLK",
                "47": "SWDIO",
                "44": "USB_DP",
                "45": "USB_DM",
            },
            power_pins={"50": "VDD_3P3", "53": "VDD_3P3", "57": "VDD_1P1", "33": "GND"},
            power_reqs=[PowerReq("VDD_3P3", 3.3, 120), PowerReq("VDD_1P1", 1.1, 80)],
            bypass_caps=[BypassCap("53", "VDD_3P3", "GND", "100nF", "Capacitor_SMD:C_0402_1005Metric")],
        )
    )

    # --- nRF52840 (QFN-73 simplified) ---
    reg.register(
        ComponentDef(
            mpn="nRF52840-QIAA",
            ref_prefix="U",
            value="nRF52840",
            footprint="Package_DFN_QFN:QFN-73-1EP_7x7mm_P0.5mm",
            description="BLE/2.4GHz SoC",
            category="digital",
            pins=[
                PinDef("12", "DEC4", "power_out", "T"),
                PinDef("13", "DCC", "power_in", "T"),
                PinDef("18", "SWDCLK", "input", "R"),
                PinDef("19", "SWDIO", "bidirectional", "R"),
                PinDef("20", "nRESET", "input", "R"),
                PinDef("34", "VDD", "power_in", "T"),
                PinDef("35", "GND", "power_in", "B"),
            ],
            pin_nets={"18": "SWCLK", "19": "SWDIO", "20": "RESET_N"},
            power_pins={"34": "VDD_3P3", "35": "GND"},
            power_reqs=[PowerReq("VDD_3P3", 3.3, 80)],
            bypass_caps=[BypassCap("34", "VDD_3P3", "GND", "100nF", "Capacitor_SMD:C_0402_1005Metric")],
        )
    )

    # --- AP2112K-3.3 LDO ---
    reg.register(
        ComponentDef(
            mpn="AP2112K-3.3TRG1",
            ref_prefix="U",
            value="AP2112K-3.3",
            footprint="Package_TO_SOT_SMD:SOT-23-5",
            description="600mA LDO regulator",
            category="power",
            pins=[
                PinDef("1", "VIN", "power_in", "L"),
                PinDef("2", "GND", "power_in", "B"),
                PinDef("3", "EN", "input", "L"),
                PinDef("5", "VOUT", "power_out", "R"),
            ],
            pin_nets={"3": "REG_EN"},
            power_pins={"1": "VIN", "2": "GND", "5": "VDD_3P3"},
            power_reqs=[PowerReq("VIN", 5.0, 600)],
            bypass_caps=[BypassCap("5", "VDD_3P3", "GND", "10uF", "Capacitor_SMD:C_0805_2012Metric")],
        )
    )

    # --- MCP1700-3302E ---
    reg.register(
        ComponentDef(
            mpn="MCP1700-3302E",
            ref_prefix="U",
            value="MCP1700-3.3",
            footprint="Package_TO_SOT_SMD:SOT-23",
            description="250mA LDO regulator",
            category="power",
            pins=[
                PinDef("1", "GND", "power_in", "B"),
                PinDef("2", "VIN", "power_in", "L"),
                PinDef("3", "VOUT", "power_out", "R"),
            ],
            power_pins={"1": "GND", "2": "VIN", "3": "VDD_3P3"},
            power_reqs=[PowerReq("VIN", 5.0, 250)],
            bypass_caps=[BypassCap("3", "VDD_3P3", "GND", "1uF", "Capacitor_SMD:C_0603_1608Metric")],
        )
    )

    # --- RT6150 Buck-Boost (simplified) ---
    reg.register(
        ComponentDef(
            mpn="RT6150A",
            ref_prefix="U",
            value="RT6150A",
            footprint="Package_DFN_QFN:WDFN-10-1EP_3x3mm_P0.5mm",
            description="Synchronous buck-boost converter",
            category="power",
            pins=[
                PinDef("1", "VIN", "power_in", "L"),
                PinDef("2", "EN", "input", "L"),
                PinDef("4", "SW", "power_out", "R"),
                PinDef("7", "VOUT", "power_out", "R"),
                PinDef("8", "FB", "input", "R"),
                PinDef("10", "GND", "power_in", "B"),
            ],
            pin_nets={"2": "REG_EN", "8": "FB"},
            power_pins={"1": "VIN", "7": "VDD_3P3", "10": "GND"},
            power_reqs=[PowerReq("VIN", 5.0, 2000)],
        )
    )

    # --- TPS63020 Buck-Boost (simplified) ---
    reg.register(
        ComponentDef(
            mpn="TPS63020DSJR",
            ref_prefix="U",
            value="TPS63020",
            footprint="Package_TO_SOT_SMD:WSON-14-1EP_3x4mm_P0.5mm",
            description="Buck-boost converter 4A switch",
            category="power",
            pins=[
                PinDef("1", "L1", "power_out", "L"),
                PinDef("3", "VIN", "power_in", "L"),
                PinDef("5", "EN", "input", "L"),
                PinDef("7", "VOUT", "power_out", "R"),
                PinDef("10", "FB", "input", "R"),
                PinDef("14", "GND", "power_in", "B"),
            ],
            pin_nets={"5": "REG_EN", "10": "FB"},
            power_pins={"3": "VIN", "7": "VDD_3P3", "14": "GND"},
            power_reqs=[PowerReq("VIN", 5.0, 2000)],
        )
    )

    # --- microSD Card Slot ---
    reg.register(
        ComponentDef(
            mpn="microSD-slot",
            ref_prefix="J",
            value="microSD",
            footprint="Connector_Card:microSD_HC_Hirose_DM3AT-SF-PEJM5",
            description="microSD Card Slot",
            category="connector",
            pins=[
                PinDef("1", "SD_D2", "bidirectional", "L"),
                PinDef("2", "SD_D3", "bidirectional", "L"),
                PinDef("3", "SD_CMD", "bidirectional", "L"),
                PinDef("4", "VDD", "power_in", "T"),
                PinDef("5", "SD_CLK", "input", "L"),
                PinDef("6", "GND", "power_in", "B"),
                PinDef("7", "SD_D0", "bidirectional", "R"),
                PinDef("8", "SD_D1", "bidirectional", "R"),
                PinDef("9", "SD_CD", "output", "R"),
            ],
            pin_nets={
                "1": "SD_D2",
                "2": "SD_D3",
                "3": "SD_CMD",
                "5": "SD_CLK",
                "7": "SD_D0",
                "8": "SD_D1",
                "9": "SD_CD",
            },
            power_pins={"4": "VDD_3P3", "6": "GND"},
            bypass_caps=[
                BypassCap("4", "VDD_3P3", "GND", "10uF", "Capacitor_SMD:C_0805_2012Metric"),
            ],
        )
    )

    # --- SWD/JTAG Debug Header (10-pin) ---
    reg.register(
        ComponentDef(
            mpn="SWD-10PIN",
            ref_prefix="J",
            value="SWD Header",
            footprint="Connector_PinHeader_1.27mm:PinHeader_2x05_P1.27mm_Vertical_SMD",
            description="ARM SWD Debug Header 10-pin",
            category="debug",
            pins=[
                PinDef("1", "VCC", "power_out", "T"),
                PinDef("2", "SWDIO", "bidirectional", "R"),
                PinDef("3", "GND", "power_in", "B"),
                PinDef("4", "SWCLK", "input", "R"),
                PinDef("5", "GND2", "power_in", "B"),
                PinDef("6", "SWO", "output", "R"),
                PinDef("7", "KEY", "passive", "L"),
                PinDef("8", "NC", "passive", "L"),
                PinDef("9", "GND3", "power_in", "B"),
                PinDef("10", "RESET", "output", "R"),
            ],
            pin_nets={"2": "SWDIO", "4": "SWCLK", "6": "SWO", "10": "RESET_N"},
            power_pins={"1": "VDD_3P3", "3": "GND", "5": "GND", "9": "GND"},
        )
    )

    # --- JTAG Header (2x7, 2.54mm simplified) ---
    reg.register(
        ComponentDef(
            mpn="JTAG-14PIN",
            ref_prefix="J",
            value="JTAG Header",
            footprint="Connector_PinHeader_2.54mm:PinHeader_2x07_P2.54mm_Vertical",
            description="ARM 14-pin JTAG header",
            category="debug",
            pins=[
                PinDef("1", "VREF", "power_out", "T"),
                PinDef("3", "nTRST", "input", "L"),
                PinDef("5", "TDI", "input", "L"),
                PinDef("7", "TMS", "input", "L"),
                PinDef("9", "TCK", "input", "R"),
                PinDef("13", "TDO", "output", "R"),
                PinDef("4", "GND", "power_in", "B"),
                PinDef("6", "GND2", "power_in", "B"),
            ],
            pin_nets={
                "3": "JTAG_TRST_N",
                "5": "JTAG_TDI",
                "7": "JTAG_TMS",
                "9": "JTAG_TCK",
                "13": "JTAG_TDO",
            },
            power_pins={"1": "VDD_3P3", "4": "GND", "6": "GND"},
        )
    )

    # --- Generic pin header 1x08 ---
    reg.register(
        ComponentDef(
            mpn="PINHDR-1x08-2.54",
            ref_prefix="J",
            value="PinHeader 1x08",
            footprint="Connector_PinHeader_2.54mm:PinHeader_1x08_P2.54mm_Vertical",
            description="Generic 1x08 pin header",
            category="connector",
            pins=[PinDef(str(i), f"PIN{i}", "bidirectional", "L" if i <= 4 else "R") for i in range(1, 9)],
        )
    )

    # --- SMA Connector ---
    reg.register(
        ComponentDef(
            mpn="SMA-EDGE",
            ref_prefix="J",
            value="SMA",
            footprint="Connector_Coaxial:SMA_Amphenol_132134_EdgeMount",
            description="RF SMA edge connector",
            category="connector",
            pins=[
                PinDef("1", "SIG", "passive", "R"),
                PinDef("2", "GND", "power_in", "B"),
            ],
            pin_nets={"1": "RF_IN"},
            power_pins={"2": "GND"},
        )
    )

    # --- RJ45 MagJack (simplified pins) ---
    reg.register(
        ComponentDef(
            mpn="RJ45-MAGJACK",
            ref_prefix="J",
            value="RJ45",
            footprint="Connector_RJ:RJ45_Amphenol_RJMG1BD3B8K1ANR",
            description="RJ45 connector with integrated magnetics",
            category="connector",
            pins=[
                PinDef("1", "TX+", "bidirectional", "L"),
                PinDef("2", "TX-", "bidirectional", "L"),
                PinDef("3", "RX+", "bidirectional", "R"),
                PinDef("6", "RX-", "bidirectional", "R"),
                PinDef("7", "GND", "power_in", "B"),
            ],
            pin_nets={"1": "ETH_TX_P", "2": "ETH_TX_N", "3": "ETH_RX_P", "6": "ETH_RX_N"},
            power_pins={"7": "GND"},
        )
    )

    # --- MPU6050 IMU (QFN-24 simplified) ---
    reg.register(
        ComponentDef(
            mpn="MPU6050",
            ref_prefix="U",
            value="MPU6050",
            footprint="Package_DFN_QFN:QFN-24-1EP_4x4mm_P0.5mm_EP2.7x2.7mm",
            description="6-axis accelerometer/gyroscope",
            category="sensor",
            pins=[
                PinDef("1", "CLKIN", "input", "L"),
                PinDef("8", "VDD", "power_in", "T"),
                PinDef("9", "GND", "power_in", "B"),
                PinDef("23", "SCL", "input", "L"),
                PinDef("24", "SDA", "bidirectional", "R"),
                PinDef("12", "INT", "output", "R"),
            ],
            pin_nets={"23": "I2C_SCL", "24": "I2C_SDA", "12": "IMU_INT"},
            power_pins={"8": "VDD_3P3", "9": "GND"},
            power_reqs=[PowerReq("VDD_3P3", 3.3, 10)],
            bypass_caps=[BypassCap("8", "VDD_3P3", "GND", "100nF", "Capacitor_SMD:C_0402_1005Metric")],
        )
    )

    # --- MAX17048 Fuel Gauge (TDFN-8 simplified) ---
    reg.register(
        ComponentDef(
            mpn="MAX17048G+T10",
            ref_prefix="U",
            value="MAX17048",
            footprint="Package_DFN_QFN:TDFN-8-1EP_2x3mm_P0.5mm_EP1.4x1.6mm",
            description="Li-ion fuel gauge",
            category="sensor",
            pins=[
                PinDef("1", "CELL", "input", "L"),
                PinDef("2", "GND", "power_in", "B"),
                PinDef("3", "SCL", "input", "L"),
                PinDef("4", "SDA", "bidirectional", "R"),
                PinDef("5", "ALRT", "output", "R"),
                PinDef("8", "VDD", "power_in", "T"),
            ],
            pin_nets={"3": "I2C_SCL", "4": "I2C_SDA", "5": "FUEL_ALRT"},
            power_pins={"2": "GND", "8": "VDD_3P3"},
            power_reqs=[PowerReq("VDD_3P3", 3.3, 1)],
            bypass_caps=[BypassCap("8", "VDD_3P3", "GND", "100nF", "Capacitor_SMD:C_0402_1005Metric")],
        )
    )

    # --- Status LED (2-pin) ---
    reg.register(
        ComponentDef(
            mpn="LED-0603",
            ref_prefix="D",
            value="Green LED",
            footprint="LED_SMD:LED_0603_1608Metric",
            description="Status LED Green 0603",
            category="debug",
            pins=[
                PinDef("1", "A", "passive", "L"),
                PinDef("2", "K", "passive", "R"),
            ],
            pin_nets={"1": "LED_A", "2": "LED_K"},
            straps=[
                StrapConfig("1", "LED_A", "VDD_3P3", "330R", "Resistor_SMD:R_0402_1005Metric"),
            ],
        )
    )

    return reg


# Module-level default registry
BUILTIN_REGISTRY = _builtin_components()
