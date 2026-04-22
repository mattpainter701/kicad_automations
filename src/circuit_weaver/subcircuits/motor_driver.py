"""H-Bridge / stepper motor driver subcircuit template.

Generates a complete dual H-bridge motor driver subcircuit from design
parameters: supply voltage, motor current.

Supports DRV8833 (default) and TB6612FNG topologies.

Auto-calculates: current-sense resistors (DRV8833), decoupling caps,
pull-up resistors. All values snapped to standard E96 series.
"""

from __future__ import annotations

from typing import Any

from ..component_db import BypassCap, ComponentDef, PinDef, StrapConfig
from .base import (
    FP_0402R,
    BoundaryPort,
    SubcircuitResult,
    SubcircuitTemplate,
    cap_footprint,
    format_capacitance,
    format_resistance,
    res_footprint,
    snap_to_e96,
)

# Known motor driver ICs and their parameters
MOTOR_DRIVER_IC_DATABASE = {
    "DRV8833": {
        "description": "Dual H-Bridge Motor Driver 2A WSON-10",
        "footprint": "Package_SO:VSSOP-10_3x3mm_P0.5mm",
        "vin_range": (2.7, 10.8),
        "ipeak": 2.0,  # 2A peak per channel
        "has_current_sense": True,
        "vref_isense": 0.200,  # 200mV trip point
        "pins": [
            PinDef("1", "nSLEEP", "input", "L"),
            PinDef("2", "ISENA", "input", "B"),
            PinDef("3", "OUT1", "output", "R"),
            PinDef("4", "OUT2", "output", "R"),
            PinDef("5", "VM", "power_in", "T"),
            PinDef("6", "GND", "power_in", "B"),
            PinDef("7", "OUT3", "output", "R"),
            PinDef("8", "OUT4", "output", "R"),
            PinDef("9", "ISENB", "input", "B"),
            PinDef("10", "nFAULT", "output", "R"),
            PinDef("11", "IN1", "input", "L"),
            PinDef("12", "IN2", "input", "L"),
            PinDef("13", "IN3", "input", "L"),
            PinDef("14", "IN4", "input", "L"),
            PinDef("15", "EPAD", "power_in", "B"),
        ],
        "pin_vm": "5",
        "pin_gnd": "6",
        "pin_epad": "15",
        "pin_nsleep": "1",
        "pin_nfault": "10",
        "pin_isena": "2",
        "pin_isenb": "9",
        "pin_in1": "11",
        "pin_in2": "12",
        "pin_in3": "13",
        "pin_in4": "14",
        "pin_out1": "3",
        "pin_out2": "4",
        "pin_out3": "7",
        "pin_out4": "8",
        "has_vcc": False,
    },
    "TB6612FNG": {
        "description": "Dual H-Bridge Motor Driver 1.2A SSOP-24",
        "footprint": "Package_SO:SSOP-24_5.3x8.2mm_P0.65mm",
        "vin_range": (2.5, 13.5),
        "ipeak": 3.2,  # 3.2A peak, 1.2A continuous
        "has_current_sense": False,
        "pins": [
            PinDef("1", "AO1", "output", "R"),
            PinDef("2", "AO2", "output", "R"),
            PinDef("3", "GND", "power_in", "B"),
            PinDef("4", "GND", "power_in", "B"),
            PinDef("5", "BO2", "output", "R"),
            PinDef("6", "BO1", "output", "R"),
            PinDef("7", "VM", "power_in", "T"),
            PinDef("8", "VCC", "power_in", "T"),
            PinDef("9", "GND", "power_in", "B"),
            PinDef("10", "GND", "power_in", "B"),
            PinDef("11", "PWMA", "input", "L"),
            PinDef("12", "AIN2", "input", "L"),
            PinDef("13", "AIN1", "input", "L"),
            PinDef("14", "STBY", "input", "L"),
            PinDef("15", "BIN1", "input", "L"),
            PinDef("16", "BIN2", "input", "L"),
            PinDef("17", "PWMB", "input", "L"),
            PinDef("18", "GND", "power_in", "B"),
            PinDef("19", "GND", "power_in", "B"),
            PinDef("20", "GND", "power_in", "B"),
            PinDef("21", "GND", "power_in", "B"),
            PinDef("22", "GND", "power_in", "B"),
            PinDef("23", "GND", "power_in", "B"),
            PinDef("24", "GND", "power_in", "B"),
        ],
        "pin_vm": "7",
        "pin_vcc": "8",
        "pin_gnd": "3",
        "pin_stby": "14",
        "pin_ain1": "13",
        "pin_ain2": "12",
        "pin_pwma": "11",
        "pin_bin1": "15",
        "pin_bin2": "16",
        "pin_pwmb": "17",
        "pin_ao1": "1",
        "pin_ao2": "2",
        "pin_bo1": "6",
        "pin_bo2": "5",
        "has_vcc": True,
    },
}


class MotorDriverTemplate(SubcircuitTemplate):
    """Dual H-bridge motor driver with auto-calculated current sense."""

    template_type = "motor_driver"
    description = "Dual H-bridge motor driver with optional current limiting"
    param_schema = [
        {
            "name": "vm",
            "type": "number",
            "required": True,
            "description": "Motor supply voltage in volts",
        },
        {
            "name": "imotor",
            "type": "number",
            "required": True,
            "description": "Motor current per channel in amps",
        },
        {
            "name": "ic",
            "type": "string",
            "required": False,
            "default": "DRV8833",
            "description": "Motor driver IC MPN",
        },
        {
            "name": "ref",
            "type": "string",
            "required": False,
            "default": "U",
            "description": "Reference designator for the IC",
        },
        {
            "name": "vm_net",
            "type": "string",
            "required": False,
            "default": "VMOT",
            "description": "Motor supply net name",
        },
        {
            "name": "vdd_net",
            "type": "string",
            "required": False,
            "default": "VDD_3P3",
            "description": "Logic supply net name (TB6612 VCC)",
        },
        {
            "name": "motor_type",
            "type": "string",
            "required": False,
            "default": "dc",
            "description": "Motor type: 'dc' or 'stepper'",
        },
    ]

    @staticmethod
    def _ic_db() -> dict[str, dict[str, Any]]:
        """Hardcoded MOTOR_DRIVER_IC_DATABASE merged with ic_data 'motor_driver'
        entries so user :func:`register_ic` calls work with the legacy template
        too. Sprint 37 Task 158."""
        from ..ic_data import merge_into_legacy_db

        return merge_into_legacy_db(MOTOR_DRIVER_IC_DATABASE, "motor_driver")

    def validate_params(self, params: dict[str, Any]) -> list[str]:
        errors = []
        vm = params.get("vm")
        imotor = params.get("imotor")
        if vm is None:
            errors.append("Missing required param 'vm' (motor supply voltage in V)")
        if imotor is None:
            errors.append("Missing required param 'imotor' (motor current in A)")

        ic_name = params.get("ic", "DRV8833")
        db = self._ic_db()
        if ic_name not in db:
            errors.append(f"Unknown motor driver IC '{ic_name}'. Available: {', '.join(db)}")
            return errors

        ic_db = db[ic_name]
        if vm is not None:
            vin_min, vin_max = ic_db["vin_range"]
            if vm < vin_min or vm > vin_max:
                errors.append(f"vm ({vm}V) outside {ic_name} supply range ({vin_min}-{vin_max}V)")
        if imotor is not None:
            if imotor <= 0:
                errors.append(f"imotor ({imotor}A) must be positive")
            elif imotor > ic_db["ipeak"]:
                errors.append(f"imotor ({imotor}A) exceeds {ic_name} peak rating ({ic_db['ipeak']}A)")
        return errors

    def generate(self, params: dict[str, Any]) -> SubcircuitResult:
        """Generate a motor driver subcircuit.

        Required params:
            vm: float -- motor supply voltage (V)
            imotor: float -- motor current per channel (A)

        Optional params:
            ic: str -- IC MPN (default: "DRV8833")
            ref: str -- reference designator (default: "U")
            vm_net: str -- motor supply net (default: "VMOT")
            vdd_net: str -- logic supply net (default: "VDD_3P3")
            motor_type: str -- 'dc' or 'stepper' (default: "dc")
        """
        vm = params["vm"]
        imotor = params["imotor"]
        ic_name = params.get("ic", "DRV8833")
        ref = params.get("ref", "U")
        vm_net = params.get("vm_net", "VMOT")
        vdd_net = params.get("vdd_net", "VDD_3P3")
        motor_type = params.get("motor_type", "dc")

        db = self._ic_db()
        ic_db = db.get(ic_name, db["DRV8833"])

        if ic_name == "DRV8833":
            return self._generate_drv8833(ic_name, ic_db, vm, imotor, ref, vm_net, motor_type)
        else:
            return self._generate_tb6612(ic_name, ic_db, vm, imotor, ref, vm_net, vdd_net, motor_type)

    def _generate_drv8833(
        self,
        ic_name: str,
        ic_db: dict,
        vm: float,
        imotor: float,
        ref: str,
        vm_net: str,
        motor_type: str,
    ) -> SubcircuitResult:
        """Generate DRV8833 dual H-bridge with current sense resistors."""

        # ---- Calculate passive values ----

        # Current sense resistor: Ichop = Vref / Rsense => Rsense = Vref / Imotor
        vref_isense = ic_db["vref_isense"]
        rsense_raw = vref_isense / imotor
        rsense = snap_to_e96(rsense_raw)
        actual_ichop = vref_isense / rsense
        rsense_power = imotor * imotor * rsense

        # nSLEEP pull-up: 10k to VM (keep IC awake by default)
        r_pullup = snap_to_e96(10e3)

        # VM bulk decoupling: 100uF + 100nF
        c_bulk = 100e-6
        c_hf = 100e-9

        # ---- Net names (unique per instance) ----
        isena_net = f"ISENA_{ref}"
        isenb_net = f"ISENB_{ref}"
        nsleep_net = f"nSLEEP_{ref}"
        nfault_net = f"nFAULT_{ref}"
        out1_net = f"MOTA_P_{ref}"
        out2_net = f"MOTA_N_{ref}"
        out3_net = f"MOTB_P_{ref}"
        out4_net = f"MOTB_N_{ref}"
        in1_net = f"IN1_{ref}"
        in2_net = f"IN2_{ref}"
        in3_net = f"IN3_{ref}"
        in4_net = f"IN4_{ref}"

        # ---- Build IC component ----
        power_pins = {
            ic_db["pin_vm"]: vm_net,
            ic_db["pin_gnd"]: "GND",
            ic_db["pin_epad"]: "GND",
        }

        pin_nets = {
            ic_db["pin_nsleep"]: nsleep_net,
            ic_db["pin_nfault"]: nfault_net,
            ic_db["pin_isena"]: isena_net,
            ic_db["pin_isenb"]: isenb_net,
            ic_db["pin_in1"]: in1_net,
            ic_db["pin_in2"]: in2_net,
            ic_db["pin_in3"]: in3_net,
            ic_db["pin_in4"]: in4_net,
            ic_db["pin_out1"]: out1_net,
            ic_db["pin_out2"]: out2_net,
            ic_db["pin_out3"]: out3_net,
            ic_db["pin_out4"]: out4_net,
        }

        bypass_caps = [
            BypassCap(
                "CVM_BULK",
                vm_net,
                "GND",
                format_capacitance(c_bulk),
                cap_footprint(c_bulk),
                role="input_bulk",
                presentation="topology_local",
            ),
            BypassCap(
                "CVM_HF",
                vm_net,
                "GND",
                format_capacitance(c_hf),
                cap_footprint(c_hf),
                role="input_cap",
                presentation="topology_local",
            ),
        ]

        straps = [
            StrapConfig(
                "RSENSA",
                isena_net,
                "GND",
                format_resistance(rsense),
                res_footprint(rsense, rsense_power),
                role="current_sense",
                presentation="topology_local",
            ),
            StrapConfig(
                "RSENB",
                isenb_net,
                "GND",
                format_resistance(rsense),
                res_footprint(rsense, rsense_power),
                role="current_sense",
                presentation="topology_local",
            ),
            StrapConfig(
                "R_NSLEEP",
                nsleep_net,
                vm_net,
                format_resistance(r_pullup),
                FP_0402R,
                role="pull_up",
                presentation="topology_local",
            ),
        ]

        annotations = [
            f"Motor driver {ic_name}: {motor_type} mode, VM={vm}V",
            f"Ichop = {vref_isense}V / {format_resistance(rsense)} = {actual_ichop:.3f}A",
            f"Rsense power = {rsense_power * 1e3:.1f}mW",
            f"Cin={format_capacitance(c_bulk)} + {format_capacitance(c_hf)}",
        ]

        ic_comp = ComponentDef(
            mpn=ic_name,
            ref_prefix="U",
            value=ic_name,
            footprint=ic_db["footprint"],
            description=ic_db["description"],
            category="motor",
            pins=list(ic_db["pins"]),
            power_pins=power_pins,
            pin_nets=pin_nets,
            bypass_caps=bypass_caps,
            straps=straps,
            annotations=annotations,
        )
        ic_comp.source_ref = ref

        # ---- Boundary ports ----
        ports = [
            BoundaryPort(vm_net, "input"),
            BoundaryPort("GND", "passive"),
            BoundaryPort(out1_net, "output"),
            BoundaryPort(out2_net, "output"),
            BoundaryPort(out3_net, "output"),
            BoundaryPort(out4_net, "output"),
            BoundaryPort(in1_net, "input"),
            BoundaryPort(in2_net, "input"),
            BoundaryPort(in3_net, "input"),
            BoundaryPort(in4_net, "input"),
            BoundaryPort(nsleep_net, "input"),
            BoundaryPort(nfault_net, "output"),
        ]

        return SubcircuitResult(
            components=[ic_comp],
            boundary_ports=ports,
            annotations=[
                f"Motor Driver {ic_name}: VM={vm}V, Ichop={actual_ichop:.2f}A/ch ({motor_type})",
            ],
            primary_category="motor",
        )

    def _generate_tb6612(
        self,
        ic_name: str,
        ic_db: dict,
        vm: float,
        imotor: float,
        ref: str,
        vm_net: str,
        vdd_net: str,
        motor_type: str,
    ) -> SubcircuitResult:
        """Generate TB6612FNG dual H-bridge (no current sense)."""

        # VM bulk decoupling: 100uF + 100nF
        c_bulk = 100e-6
        c_hf = 100e-9

        # VCC logic decoupling: 100nF
        c_vcc = 100e-9

        # STBY pull-up: 10k to VCC (keep IC active by default)
        r_stby = snap_to_e96(10e3)

        # ---- Net names (unique per instance) ----
        stby_net = f"STBY_{ref}"
        ao1_net = f"MOTA_P_{ref}"
        ao2_net = f"MOTA_N_{ref}"
        bo1_net = f"MOTB_P_{ref}"
        bo2_net = f"MOTB_N_{ref}"
        ain1_net = f"AIN1_{ref}"
        ain2_net = f"AIN2_{ref}"
        pwma_net = f"PWMA_{ref}"
        bin1_net = f"BIN1_{ref}"
        bin2_net = f"BIN2_{ref}"
        pwmb_net = f"PWMB_{ref}"

        # ---- Build IC component ----
        # TB6612 has multiple GND pins — connect primary to GND,
        # rest wired via power_pins
        power_pins = {
            ic_db["pin_vm"]: vm_net,
            ic_db["pin_vcc"]: vdd_net,
            ic_db["pin_gnd"]: "GND",
            # Additional GND pins
            "4": "GND",
            "9": "GND",
            "10": "GND",
            "18": "GND",
            "19": "GND",
            "20": "GND",
            "21": "GND",
            "22": "GND",
            "23": "GND",
            "24": "GND",
        }

        pin_nets = {
            ic_db["pin_stby"]: stby_net,
            ic_db["pin_ain1"]: ain1_net,
            ic_db["pin_ain2"]: ain2_net,
            ic_db["pin_pwma"]: pwma_net,
            ic_db["pin_bin1"]: bin1_net,
            ic_db["pin_bin2"]: bin2_net,
            ic_db["pin_pwmb"]: pwmb_net,
            ic_db["pin_ao1"]: ao1_net,
            ic_db["pin_ao2"]: ao2_net,
            ic_db["pin_bo1"]: bo1_net,
            ic_db["pin_bo2"]: bo2_net,
        }

        bypass_caps = [
            BypassCap(
                "CVM_BULK",
                vm_net,
                "GND",
                format_capacitance(c_bulk),
                cap_footprint(c_bulk),
                role="input_bulk",
                presentation="topology_local",
            ),
            BypassCap(
                "CVM_HF",
                vm_net,
                "GND",
                format_capacitance(c_hf),
                cap_footprint(c_hf),
                role="input_cap",
                presentation="topology_local",
            ),
            BypassCap(
                "CVCC",
                vdd_net,
                "GND",
                format_capacitance(c_vcc),
                cap_footprint(c_vcc),
                role="decoupling",
                presentation="topology_local",
            ),
        ]

        straps = [
            StrapConfig(
                "R_STBY",
                stby_net,
                vdd_net,
                format_resistance(r_stby),
                FP_0402R,
                role="pull_up",
                presentation="topology_local",
            ),
        ]

        annotations = [
            f"Motor driver {ic_name}: {motor_type} mode, VM={vm}V, VCC={vdd_net}",
            f"Max continuous current: 1.2A/ch, peak: {ic_db['ipeak']}A",
            f"Cin={format_capacitance(c_bulk)} + {format_capacitance(c_hf)}, Cvcc={format_capacitance(c_vcc)}",
            "No current sense — use external shunt if chopping needed",
        ]

        ic_comp = ComponentDef(
            mpn=ic_name,
            ref_prefix="U",
            value=ic_name,
            footprint=ic_db["footprint"],
            description=ic_db["description"],
            category="motor",
            pins=list(ic_db["pins"]),
            power_pins=power_pins,
            pin_nets=pin_nets,
            bypass_caps=bypass_caps,
            straps=straps,
            annotations=annotations,
        )
        ic_comp.source_ref = ref

        # ---- Boundary ports ----
        ports = [
            BoundaryPort(vm_net, "input"),
            BoundaryPort(vdd_net, "input"),
            BoundaryPort("GND", "passive"),
            BoundaryPort(ao1_net, "output"),
            BoundaryPort(ao2_net, "output"),
            BoundaryPort(bo1_net, "output"),
            BoundaryPort(bo2_net, "output"),
            BoundaryPort(ain1_net, "input"),
            BoundaryPort(ain2_net, "input"),
            BoundaryPort(pwma_net, "input"),
            BoundaryPort(bin1_net, "input"),
            BoundaryPort(bin2_net, "input"),
            BoundaryPort(pwmb_net, "input"),
            BoundaryPort(stby_net, "input"),
        ]

        return SubcircuitResult(
            components=[ic_comp],
            boundary_ports=ports,
            annotations=[
                f"Motor Driver {ic_name}: VM={vm}V, Imax=1.2A/ch ({motor_type})",
            ],
            primary_category="motor",
        )
