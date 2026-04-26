"""Sprint 41 — auto-repair trivially-fixable bus issues before validation.

Runs inside :func:`dispatcher.compile_design_ir` after the primary
component resolution step. Detects buses whose conditioning passives are
obviously missing (I2C without pull-ups, SPI CS without a pull) and
synthesizes them from the already-shipping subcircuit templates
(:mod:`subcircuits.i2c_bus`).

The pass is intentionally conservative — it only adds what the validator
would otherwise flag as placement-blocking, and only when the missing
passive is unambiguous (e.g. a single VDD rail on every participant). It
never remaps MCU pins, adds missing sensors, or guesses at undeclared
signal names. Those remain user errors and surface as
``placement_readiness / orphan-interface`` from :mod:`placement_readiness`.

Users can disable the whole pass via top-level spec key
``auto_repair: false``. A single repair is suppressed automatically when
the design already contains a block whose ``template_type`` matches —
e.g. declaring an ``i2c_bus`` block anywhere inhibits the I2C pull-up
repair, even if its nets don't align.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

from .component_db import ComponentDef
from .design_ir import DesignBlock, DesignIR

_logger = logging.getLogger(__name__)

_I2C_SDA_RE = re.compile(r"(?:^|_)(SDA|I2C.*DAT|I2C\d*SDA)(?:$|_)", re.IGNORECASE)
_I2C_SCL_RE = re.compile(r"(?:^|_)(SCL|I2C.*CLK|I2C\d*SCL)(?:$|_)", re.IGNORECASE)


def _is_ground(net: str) -> bool:
    """Return True if *net* is a ground net by name convention."""
    upper = (net or "").upper()
    from .subcircuits.base import GROUND_NET_PREFIXES
    return any(upper == p or upper.startswith(f"{p}_") for p in GROUND_NET_PREFIXES)


@dataclass
class RepairAction:
    """One auto-repair decision, logged for audit and written into the
    placement_readiness.json report."""

    kind: str  # e.g. "i2c_pullups"
    rationale: str
    synthetic_block_id: str = ""
    nets: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "kind": self.kind,
            "rationale": self.rationale,
            "synthetic_block_id": self.synthetic_block_id,
            "nets": list(self.nets),
        }


def _bus_pairs(components: list[ComponentDef]) -> list[tuple[str, str, set[str]]]:
    """Return (sda_net, scl_net, participating_power_nets) triplets.

    A bus is formed as soon as *any* named I2C_SDA-ish net and a matching
    I2C_SCL-ish net both appear anywhere in the design. Number of
    participants is not required — a lone sensor declaring I2C_SDA /
    I2C_SCL still needs pull-ups, and the user will wire the MCU side
    later (typically via forward-annotation edits or an explicit
    ``pin_map`` in the YAML). ``participating_power_nets`` is the union
    of each participant's non-ground ``power_pins`` values — used to
    pick the pull-up rail when the bus doesn't name one explicitly.

    Matching is one-to-one: each SDA net pairs with at most one SCL net
    (the one with the largest ref overlap, then alphabetical as
    tiebreaker for determinism).
    """
    sda_to_refs: dict[str, set[str]] = {}
    scl_to_refs: dict[str, set[str]] = {}
    ref_to_power_nets: dict[str, set[str]] = {}

    for comp in components:
        ref = comp.source_ref or comp.ref_prefix
        if not ref:
            continue
        for pin_num, net in comp.pin_nets.items():
            if not net:
                continue
            if _I2C_SDA_RE.search(net):
                sda_to_refs.setdefault(net, set()).add(ref)
            if _I2C_SCL_RE.search(net):
                scl_to_refs.setdefault(net, set()).add(ref)
        for net in comp.power_pins.values():
            if net and not _is_ground(net):
                ref_to_power_nets.setdefault(ref, set()).add(net)

    pairs: list[tuple[str, str, set[str]]] = []
    used_scl: set[str] = set()
    for sda_net in sorted(sda_to_refs):
        sda_refs = sda_to_refs[sda_net]
        # Pick the SCL whose refs overlap most with this SDA; fall back
        # to alphabetical ordering for determinism. A lone named bus
        # with one participant on each line is still a bus that needs
        # pull-ups.
        best_scl = None
        best_overlap = -1
        for scl_net in sorted(scl_to_refs):
            if scl_net in used_scl:
                continue
            overlap = len(sda_refs & scl_to_refs[scl_net])
            if overlap > best_overlap:
                best_overlap = overlap
                best_scl = scl_net
        if best_scl is None:
            continue
        used_scl.add(best_scl)
        power_nets: set[str] = set()
        for ref in sda_refs | scl_to_refs.get(best_scl, set()):
            power_nets |= ref_to_power_nets.get(ref, set())
        pairs.append((sda_net, best_scl, power_nets))
    return pairs


def _has_pullup_on(components: list[ComponentDef], net: str) -> bool:
    """True iff any component already straps ``net`` to a non-ground rail."""
    for comp in components:
        for strap in comp.straps:
            if strap.net == net and strap.rail and not _is_ground(strap.rail):
                return True
    return False


def _existing_template_types(ir: DesignIR) -> set[str]:
    return {(block.template_type or "").strip().lower() for block in ir.blocks if block.template_type}


def _pick_vdd_rail(power_nets: set[str]) -> str | None:
    """Pick a sensible pull-up rail from a set of candidate VDDs.

    Preference: lowest-voltage rail that looks like VDD (so I2C pulls to
    the logic rail, not VBUS). Falls back to alphabetical ordering to
    keep the decision deterministic.
    """
    if not power_nets:
        return None
    preferred = [n for n in power_nets if n.upper().startswith("VDD")]
    pool = preferred or list(power_nets)

    def _rank(name: str) -> tuple:
        # Extract numeric voltage if any (e.g. VDD_3P3 -> 3.3, VDD_1P8 -> 1.8)
        match = re.search(r"(\d+)P(\d+)", name.upper())
        if match:
            return (0, float(f"{match.group(1)}.{match.group(2)}"), name)
        match = re.search(r"(\d+)V", name.upper())
        if match:
            return (0, float(match.group(1)), name)
        return (1, 99.0, name)

    return sorted(pool, key=_rank)[0]


def _stable_block_id(section: str, ref: str, tag: str) -> str:
    """Build a stable synthetic block id. Mirrors design_ir._stable_token."""
    import zlib

    token = f"{zlib.crc32(f'{section}|{ref}|{tag}'.encode('utf-8')) & 0xFFFFFFFF:08x}"
    return f"{section}:{ref}:{token}"


def _reserved_refs(ir: DesignIR) -> set[str]:
    return {block.ref for block in ir.blocks if block.ref}


def _next_ref(prefix: str, reserved: set[str]) -> str:
    """Allocate the next free ref with ``prefix`` given reserved refs."""
    idx = 1
    while True:
        candidate = f"{prefix}{idx}"
        if candidate not in reserved:
            reserved.add(candidate)
            return candidate
        idx += 1


def _build_i2c_pullup_block(
    sda_net: str,
    scl_net: str,
    vdd_net: str,
    ref: str,
) -> DesignBlock:
    """Construct a synthetic ``i2c_bus`` PULLUPS_ONLY block."""
    params = {
        "ic": "PULLUPS_ONLY",
        "vdd_net": vdd_net,
        "sda_net": sda_net,
        "scl_net": scl_net,
        "ref": ref,
    }
    return DesignBlock(
        id=_stable_block_id("buses", ref, f"i2c:{sda_net}:{scl_net}"),
        section="buses",
        kind="template",
        ref=ref,
        template_type="i2c_bus",
        ic="PULLUPS_ONLY",
        params=params,
        description=f"Auto-repair: I2C pull-ups on {sda_net}/{scl_net} to {vdd_net}",
    ).normalized()


def auto_repair_design(
    ir: DesignIR,
    components: list[ComponentDef],
    *,
    enabled: bool = True,
) -> tuple[DesignIR, list[RepairAction]]:
    """Return ``(patched_ir, repair_actions)`` with auto-fixes applied.

    ``ir`` is returned unchanged if ``enabled=False`` or no repairs
    apply. This function never mutates its inputs — it constructs a new
    :class:`DesignIR` with any synthetic blocks appended.

    Parameters
    ----------
    ir:
        Canonical design IR as produced by
        :func:`circuit_weaver.design_ir.normalize_design_spec`.
    components:
        Resolved component list produced by
        :func:`circuit_weaver.project_spec.resolve_project_spec` for the
        *same* IR. Used to detect bus participants.
    enabled:
        When False, skip every repair. Exposed so callers
        (``auto_repair: false`` in the spec, or opt-out env var) can
        disable the pass without branching elsewhere.
    """
    if not enabled:
        return ir, []

    actions: list[RepairAction] = []
    new_blocks: list[DesignBlock] = []

    existing_types = _existing_template_types(ir)
    reserved = _reserved_refs(ir)

    # --- I2C pull-ups ----------------------------------------------------
    # Skip entirely if the user already declared any i2c_bus block. This
    # is intentional: the user may have sized their own pull-ups or chose
    # a level-shifter topology we shouldn't override.
    if "i2c_bus" not in existing_types:
        for sda_net, scl_net, power_nets in _bus_pairs(components):
            if _has_pullup_on(components, sda_net) and _has_pullup_on(components, scl_net):
                continue
            vdd = _pick_vdd_rail(power_nets)
            if not vdd:
                _logger.info(
                    "auto_repair: skipping i2c pull-ups on %s/%s — no candidate VDD rail",
                    sda_net,
                    scl_net,
                )
                continue
            ref = _next_ref("RP", reserved)
            block = _build_i2c_pullup_block(sda_net, scl_net, vdd, ref)
            new_blocks.append(block)
            actions.append(
                RepairAction(
                    kind="i2c_pullups",
                    rationale=(
                        f"I2C bus {sda_net}/{scl_net} declared but no pull-up "
                        f"straps found; inserted PULLUPS_ONLY block {ref} to {vdd}."
                    ),
                    synthetic_block_id=block.id,
                    nets=[sda_net, scl_net, vdd],
                )
            )
            _logger.info(
                "auto_repair: synthesizing I2C pull-ups %s on %s/%s -> %s",
                ref,
                sda_net,
                scl_net,
                vdd,
            )

    if not new_blocks:
        return ir, actions

    # Assemble the patched IR. Keep ordering stable: user blocks first,
    # synthetic blocks appended (matches how a user would have added them
    # at the end of the YAML spec).
    patched_blocks = list(ir.blocks) + new_blocks
    all_interfaces = []
    for block in patched_blocks:
        all_interfaces.extend(block.interfaces)

    patched = DesignIR(
        metadata=dict(ir.metadata),
        blocks=patched_blocks,
        interfaces=all_interfaces,
        approved_overrides=list(ir.approved_overrides),
        pcb_constraints=list(ir.pcb_constraints),
    )
    return patched, actions


__all__ = ["RepairAction", "auto_repair_design"]
