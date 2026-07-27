"""RS-485 transceiver subcircuit template.

Generates a complete RS-485 half-duplex transceiver subcircuit with VCC
decoupling, DE/RE_N control, optional 120R termination, and optional
failsafe bias resistors.

Supports SP3485EN-L/TR (3.3V) and MAX485ESA+ (5V).
"""

from __future__ import annotations

from typing import Any

from .. import calc
from ..component_db import BypassCap, ComponentDef, StrapConfig, emit_and_retain_passive_synthesis
from .base import (
    FP_0402C,
    FP_0402R,
    BoundaryPort,
    LegacyDBProxy,
    SubcircuitResult,
    SubcircuitTemplate,
    format_capacitance,
    format_resistance,
)

# Known RS-485 transceiver ICs
RS485_TRANSCEIVER_IC_DATABASE = LegacyDBProxy("rs485_transceiver")  # backed by ic_data/*.json (Task 178)


class RS485TransceiverTemplate(SubcircuitTemplate):
    """RS-485 half-duplex transceiver with decoupling, bias, and optional termination."""

    template_type = "rs485_transceiver"
    description = "RS-485 half-duplex transceiver with failsafe bias and optional termination"
    param_schema = [
        {
            "name": "ic",
            "type": "string",
            "required": False,
            "default": "SP3485EN-L/TR",
            "description": "RS-485 transceiver IC MPN",
        },
        {
            "name": "ref",
            "type": "string",
            "required": False,
            "default": "U",
            "description": "Reference designator for the transceiver",
        },
        {
            "name": "vdd_net",
            "type": "string",
            "required": False,
            "default": "VDD_3P3",
            "description": "Supply rail net name",
        },
        {
            "name": "txd_net",
            "type": "string",
            "required": False,
            "description": "TXD signal net from MCU (connects to DI)",
        },
        {
            "name": "rxd_net",
            "type": "string",
            "required": False,
            "description": "RXD signal net to MCU (connects to RO)",
        },
        {
            "name": "de_net",
            "type": "string",
            "required": False,
            "description": "Driver enable net (active high, shared with RE_N for half-duplex)",
        },
        {
            "name": "bus_net_prefix",
            "type": "string",
            "required": False,
            "default": "RS485",
            "description": "Prefix for A/B bus nets",
        },
        {
            "name": "termination",
            "type": "boolean",
            "required": False,
            "default": False,
            "description": "Enable 120R termination between A and B",
        },
        {
            "name": "failsafe_bias",
            "type": "boolean",
            "required": False,
            "default": True,
            "description": "Enable failsafe bias resistors (A pull-up, B pull-down)",
        },
    ]

    def validate_params(self, params: dict[str, Any]) -> list[str]:
        errors = []
        ic_name = params.get("ic", "SP3485EN-L/TR")
        if ic_name not in RS485_TRANSCEIVER_IC_DATABASE:
            errors.append(
                f"Unknown RS-485 transceiver '{ic_name}'. Supported: {', '.join(RS485_TRANSCEIVER_IC_DATABASE)}"
            )
        return errors

    def generate(self, params: dict[str, Any]) -> SubcircuitResult:
        """Generate an RS-485 transceiver subcircuit.

        Required params: (none -- all have defaults)

        Optional params:
            ic: str -- IC MPN (default: "SP3485EN-L/TR")
            ref: str -- reference designator (default: "U")
            vdd_net: str -- supply rail (default: "VDD_3P3")
            txd_net: str -- TXD net from MCU
            rxd_net: str -- RXD net to MCU
            de_net: str -- driver enable net (shared DE/RE_N for half-duplex)
            bus_net_prefix: str -- prefix for bus nets (default: "RS485")
            termination: bool -- 120R termination (default: False)
            failsafe_bias: bool -- failsafe bias resistors (default: True)
        """
        ic_name = params.get("ic", "SP3485EN-L/TR")
        ic_db = RS485_TRANSCEIVER_IC_DATABASE.get(ic_name, RS485_TRANSCEIVER_IC_DATABASE["SP3485EN-L/TR"])
        ref = params.get("ref", "U")
        vdd_net = params.get("vdd_net", "VDD_3P3")
        txd_net = params.get("txd_net", f"RS485_TXD_{ref}")
        rxd_net = params.get("rxd_net", f"RS485_RXD_{ref}")
        de_net = params.get("de_net", f"RS485_DE_{ref}")
        bus_prefix = params.get("bus_net_prefix", "RS485")
        termination = params.get("termination", False)
        failsafe_bias = params.get("failsafe_bias", True)

        # ---- Net names (unique per instance) ----
        a_net = f"{bus_prefix}_A_{ref}"
        b_net = f"{bus_prefix}_B_{ref}"

        # ---- Power pins ----
        power_pins = {
            ic_db["pin_vcc"]: vdd_net,
            ic_db["pin_gnd"]: "GND",
        }

        # ---- Signal pin nets ----
        # Half-duplex: DE and RE_N share the same control net
        pin_nets = {
            ic_db["pin_di"]: txd_net,
            ic_db["pin_ro"]: rxd_net,
            ic_db["pin_de"]: de_net,
            ic_db["pin_re_n"]: de_net,
            ic_db["pin_a"]: a_net,
            ic_db["pin_b"]: b_net,
        }

        # ---- Annotations ----
        annotations = [
            f"RS-485 {ic_name}: {ic_db['vdd']}V half-duplex, {ic_db['speed_mbps']}Mbps",
            f"Failsafe bias: {'390R pull-up A, 390R pull-down B' if failsafe_bias else 'none'}",
            f"Termination: {'120R A-B' if termination else 'none'}",
        ]

        # ---- Build IC component ----
        ic_comp = ComponentDef(
            mpn=ic_name,
            ref_prefix="U",
            value=ic_name,
            footprint=ic_db["footprint"],
            description=ic_db["description"],
            category="digital",
            pins=list(ic_db["pins"]),
            power_pins=power_pins,
            pin_nets=pin_nets,
            bypass_caps=[],
            straps=[],
            annotations=annotations,
        )
        ic_comp.source_ref = ref

        def retain(decision: calc.PassiveSelectionDecision) -> calc.CalculationRecord:
            emitted = emit_and_retain_passive_synthesis(
                ic_comp,
                decision.calculation,
                finding=decision.finding,
            )
            assert isinstance(emitted, calc.CalculationRecord)
            return emitted

        def trace(record: calc.CalculationRecord) -> dict[str, object]:
            return {
                "selection_policy": record.policy,
                "confidence": record.confidence,
                "calculation_id": record.id,
                "evidence_ids": (record.emits_evidence,) if record.emits_evidence else (),
            }

        # The generic rail decoupler is an explicit bounded heuristic, never
        # an unlabelled universal default.
        decoupling = retain(
            calc.bounded_fallback_scalar(
                target=f"param:{ref}.power.decoupling",
                value=100e-9,
                minimum=10e-9,
                maximum=1e-6,
                unit="F",
                series="E24",
                direction="up",
            )
        )
        ic_comp.bypass_caps.append(
            BypassCap(
                "C_VCC",
                vdd_net,
                "GND",
                format_capacitance(calc.require_selection(decoupling).value),
                FP_0402C,
                role="decoupling",
                presentation="topology_local",
                **trace(decoupling),
            )
        )

        # A supplied bus impedance is equation-backed.  With no impedance
        # input, the conventional 120-ohm value remains an explicit bounded
        # heuristic so downstream confidence reporting cannot mistake it for
        # a datasheet fact.
        if termination:
            if "bus_impedance_ohm" in params:
                termination_record = calc.termination_resistor_match(
                    target=f"param:{ref}.interface.termination",
                    impedance_ohm=float(params["bus_impedance_ohm"]),
                    series="E24",
                )
                finding = None
                if not 80.0 <= termination_record.raw_result.value <= 150.0:
                    termination_record, finding = calc.withhold_calculation(
                        termination_record,
                        reason="out_of_range",
                        expected_min=80.0,
                        expected_max=150.0,
                        expected_unit="ohm",
                        observed_value=termination_record.raw_result.value,
                    )
                emitted = emit_and_retain_passive_synthesis(ic_comp, termination_record, finding=finding)
                assert isinstance(emitted, calc.CalculationRecord)
                termination_record = emitted
            else:
                termination_record = retain(
                    calc.bounded_fallback_scalar(
                        target=f"param:{ref}.interface.termination",
                        value=120.0,
                        minimum=100.0,
                        maximum=130.0,
                        unit="ohm",
                        series="E24",
                    )
                )
            if calc.is_selection_eligible(termination_record):
                ic_comp.straps.append(
                    StrapConfig(
                        "RT",
                        a_net,
                        b_net,
                        format_resistance(calc.require_selection(termination_record).value),
                        FP_0402R,
                        role="termination",
                        presentation="topology_local",
                        **trace(termination_record),
                    )
                )

        # Failsafe values are topology-sensitive.  Until a datasheet record is
        # present, retain the legacy value only as a declared bounded fallback.
        if failsafe_bias:
            for suffix, pin, rail in (("a", a_net, vdd_net), ("b", b_net, "GND")):
                bias_record = retain(
                    calc.bounded_fallback_scalar(
                        target=f"param:{ref}.interface.bias_{suffix}",
                        value=390.0,
                        minimum=330.0,
                        maximum=680.0,
                        unit="ohm",
                        series="E24",
                    )
                )
                ic_comp.straps.append(
                    StrapConfig(
                        f"RBIAS_{suffix.upper()}",
                        pin,
                        rail,
                        format_resistance(calc.require_selection(bias_record).value),
                        FP_0402R,
                        role="bias",
                        presentation="topology_local",
                        **trace(bias_record),
                    )
                )

        # ---- Boundary ports ----
        ports = [
            BoundaryPort(vdd_net, "input"),
            BoundaryPort("GND", "passive"),
            BoundaryPort(txd_net, "input"),
            BoundaryPort(rxd_net, "output"),
            BoundaryPort(de_net, "input"),
            BoundaryPort(a_net, "bidirectional"),
            BoundaryPort(b_net, "bidirectional"),
        ]

        return SubcircuitResult(
            components=[ic_comp],
            boundary_ports=ports,
            annotations=[
                f"RS-485 {ic_name}: {vdd_net} ({ic_db['vdd']}V) half-duplex, "
                f"{'failsafe biased' if failsafe_bias else 'no bias'}, "
                f"{'terminated' if termination else 'unterminated'}",
            ],
            primary_category="digital",
        )
