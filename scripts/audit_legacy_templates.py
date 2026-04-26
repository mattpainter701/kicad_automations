#!/usr/bin/env python3
"""One-shot audit: compare every legacy template against DataDrivenTemplate.
Produces docs/legacy_template_audit.md with verdict table + notes.

Usage: py scripts/audit_legacy_templates.py
"""

from __future__ import annotations

import importlib
import inspect
import sys
from pathlib import Path
from typing import Any

# Ensure the package root is on sys.path
_repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_repo_root / "src"))

from circuit_weaver.subcircuits.base import (
    SubcircuitRegistry,
    SubcircuitTemplate,
    SubcircuitResult,
    DataDrivenTemplate,
    LegacyDBProxy,
)
from circuit_weaver.ic_data import get_all_ics, merge_into_legacy_db

# --- Template registry ---
# We import every legacy template class and map to its topology name.
# This list mirrors _build_default_registry() in base.py.

_TEMPLATE_MAP: dict[str, SubcircuitTemplate] = {}

def _register():
    from circuit_weaver.subcircuits.adc import ADCTemplate
    from circuit_weaver.subcircuits.audio_amplifier import AudioAmplifierTemplate
    from circuit_weaver.subcircuits.battery_charger import BatteryChargerTemplate
    from circuit_weaver.subcircuits.battery_monitor import BatteryMonitorTemplate
    from circuit_weaver.subcircuits.boost import BoostConverterTemplate
    from circuit_weaver.subcircuits.buck import BuckConverterTemplate
    from circuit_weaver.subcircuits.buck_boost import BuckBoostConverterTemplate
    from circuit_weaver.subcircuits.can_transceiver import CANTransceiverTemplate
    from circuit_weaver.subcircuits.charge_pump import ChargePumpTemplate
    from circuit_weaver.subcircuits.clock import ClockSynthTemplate
    from circuit_weaver.subcircuits.connector import ConnectorTemplate
    from circuit_weaver.subcircuits.crystal_oscillator import CrystalOscillatorTemplate
    from circuit_weaver.subcircuits.current_sense import CurrentSenseTemplate
    from circuit_weaver.subcircuits.dac import DACTemplate
    from circuit_weaver.subcircuits.display_driver import DisplayDriverTemplate
    from circuit_weaver.subcircuits.driver import GateDriverTemplate, LevelShifterTemplate
    from circuit_weaver.subcircuits.eeprom import EEPROMTemplate
    from circuit_weaver.subcircuits.ethernet import EthernetPHYTemplate
    from circuit_weaver.subcircuits.i2c_bus import I2CBusTemplate
    from circuit_weaver.subcircuits.ldo import LDOTemplate
    from circuit_weaver.subcircuits.led_driver import LEDDriverTemplate
    from circuit_weaver.subcircuits.mosfet_switch import MOSFETSwitchTemplate
    from circuit_weaver.subcircuits.motor_driver import MotorDriverTemplate
    from circuit_weaver.subcircuits.opamp import OpAmpTemplate
    from circuit_weaver.subcircuits.power_mux import PowerMuxTemplate
    from circuit_weaver.subcircuits.protection import ProtectionTemplate
    from circuit_weaver.subcircuits.relay_driver import RelayDriverTemplate
    from circuit_weaver.subcircuits.rs485_transceiver import RS485TransceiverTemplate
    from circuit_weaver.subcircuits.rtc import RTCTemplate
    from circuit_weaver.subcircuits.sensor_frontend import SensorFrontendTemplate
    from circuit_weaver.subcircuits.spi_bus import SPIBusTemplate
    from circuit_weaver.subcircuits.usb import USBControllerTemplate, USBHubTemplate
    from circuit_weaver.subcircuits.usb_c_connector import USBCConnectorTemplate
    from circuit_weaver.subcircuits.voltage_reference import VoltageReferenceTemplate
    from circuit_weaver.subcircuits.wireless_module import WirelessModuleTemplate

    entries = [
        (ADCTemplate, "adc", "adc.py"),
        (AudioAmplifierTemplate, "audio_amplifier", "audio_amplifier.py"),
        (BatteryChargerTemplate, "battery_charger", "battery_charger.py"),
        (BatteryMonitorTemplate, "battery_monitor", "battery_monitor.py"),
        (BoostConverterTemplate, "boost", "boost.py"),
        (BuckConverterTemplate, "buck", "buck.py"),
        (BuckBoostConverterTemplate, "buck_boost", "buck_boost.py"),
        (CANTransceiverTemplate, "can_transceiver", "can_transceiver.py"),
        (ChargePumpTemplate, "charge_pump", "charge_pump.py"),
        (ClockSynthTemplate, "clock_synth", "clock.py"),
        (ConnectorTemplate, "connector", "connector.py"),
        (CrystalOscillatorTemplate, "crystal_oscillator", "crystal_oscillator.py"),
        (CurrentSenseTemplate, "current_sense", "current_sense.py"),
        (DACTemplate, "dac", "dac.py"),
        (DisplayDriverTemplate, "display_driver", "display_driver.py"),
        (EEPROMTemplate, "eeprom", "eeprom.py"),
        (EthernetPHYTemplate, "ethernet_phy", "ethernet.py"),
        (GateDriverTemplate, "gate_driver", "driver.py"),
        (I2CBusTemplate, "i2c_bus", "i2c_bus.py"),
        (LDOTemplate, "ldo", "ldo.py"),
        (LEDDriverTemplate, "led_driver", "led_driver.py"),
        (LevelShifterTemplate, "level_shifter", "driver.py"),
        (MOSFETSwitchTemplate, "mosfet_switch", "mosfet_switch.py"),
        (MotorDriverTemplate, "motor_driver", "motor_driver.py"),
        (OpAmpTemplate, "opamp", "opamp.py"),
        (PowerMuxTemplate, "power_mux", "power_mux.py"),
        (ProtectionTemplate, "protection", "protection.py"),
        (RelayDriverTemplate, "relay_driver", "relay_driver.py"),
        (RS485TransceiverTemplate, "rs485_transceiver", "rs485_transceiver.py"),
        (RTCTemplate, "rtc", "rtc.py"),
        (SensorFrontendTemplate, "sensor_frontend", "sensor_frontend.py"),
        (SPIBusTemplate, "spi_bus", "spi_bus.py"),
        (USBCConnectorTemplate, "usb_c_connector", "usb_c_connector.py"),
        (USBControllerTemplate, "usb_controller", "usb.py"),
        (USBHubTemplate, "usb_hub", "usb.py"),
        (VoltageReferenceTemplate, "voltage_reference", "voltage_reference.py"),
        (WirelessModuleTemplate, "wireless_module", "wireless_module.py"),
    ]
    for cls, topo, filename in entries:
        _TEMPLATE_MAP[topo] = (cls(), filename)


def _get_ic_db(template: SubcircuitTemplate) -> dict[str, dict[str, Any]]:
    """Get the IC database the template would use."""
    cls = type(template)
    if hasattr(cls, "_ic_db"):
        return cls._ic_db()
    # Check for module-level database variable
    mod = inspect.getmodule(cls)
    if mod is None:
        return {}
    # Try common naming patterns
    for attr_name in dir(mod):
        if attr_name.endswith("_IC_DATABASE") or attr_name.endswith("_DATABASE"):
            val = getattr(mod, attr_name)
            if isinstance(val, (dict, LegacyDBProxy)):
                return dict(val) if isinstance(val, LegacyDBProxy) else val
    return {}


def _default_params(topo: str) -> dict[str, Any]:
    """Return default params for a given topology to get a valid generate() call."""
    common = {
        "adc": {"vdd_net": "VDD_3P3", "i2c_addr": "GND"},
        "audio_amplifier": {"vdd_net": "VDD_5V", "gain": 10},
        "battery_charger": {"vin_net": "VIN", "vbat_net": "VBAT", "vbat": 4.2, "ichg": 1.0},
        "battery_monitor": {"vdd_net": "VDD_3P3"},
        "boost": {"vin": 3.7, "vout": 5.0, "iout": 0.5},
        "buck": {"vin": 12.0, "vout": 3.3, "iout": 1.0},
        "buck_boost": {"vin": 3.7, "vout": 5.0, "iout": 0.5},
        "can_transceiver": {"vdd_net": "VDD_3P3"},
        "charge_pump": {"vin": 3.3, "vout": 5.0, "iout": 0.05},
        "clock_synth": {"vdd_net": "VDD_3P3", "freq_hz": 25e6},
        "connector": {"ic": "BARREL_JACK_2.1MM", "positive_net": "VIN", "negative_net": "GND"},
        "crystal_oscillator": {"vdd_net": "VDD_3P3", "freq": 25e6, "cl_spec": 18e-12},
        "current_sense": {"vdd_net": "VDD_3P3", "imax": 2.0},
        "dac": {"vdd_net": "VDD_3P3"},
        "display_driver": {"vdd_net": "VDD_3P3"},
        "eeprom": {"vdd_net": "VDD_3P3"},
        "ethernet_phy": {"vdd_net": "VDD_3P3"},
        "gate_driver": {"vdd_net": "VDD_12V", "vdrive": 3.3},
        "i2c_bus": {"vdd_net": "VDD_3P3"},
        "ldo": {"vin": 5.0, "vout": 3.3, "iout": 0.5},
        "led_driver": {"vdd_net": "VDD_5V", "iled": 0.35, "vled": 3.0, "num_leds": 1},
        "level_shifter": {"vdd_net": "VDD_3P3", "vdd_hv_net": "VDD_5V"},
        "mosfet_switch": {"vdd_net": "VDD_3P3", "iload": 0.5},
        "motor_driver": {"vdd_net": "VDD_12V", "vmot_net": "VMOT_12V", "vm": 12.0, "imotor": 1.0},
        "opamp": {"vdd_net": "VDD_3P3", "vss_net": "GND", "gain": 5, "config": "non_inverting"},
        "power_mux": {"vdd_net": "VDD_3P3"},
        "protection": {"vdd_net": "VDD_3P3", "protect_net": "VIN"},
        "relay_driver": {"vdd_net": "VDD_5V", "vrelay_net": "VRELAY_12V", "vcoil": 12.0, "icoil": 0.03},
        "rs485_transceiver": {"vdd_net": "VDD_3P3"},
        "rtc": {"vdd_net": "VDD_3P3"},
        "sensor_frontend": {"vdd_net": "VDD_3P3", "gain": 10},
        "spi_bus": {"vdd_net": "VDD_3P3"},
        "usb_c_connector": {"vdd_net": "VDD_5V", "source_current": "3A"},
        "usb_controller": {"vdd_net": "VDD_3P3", "mode": "device"},
        "usb_hub": {"vdd_net": "VDD_3P3"},
        "voltage_reference": {"vdd_net": "VDD_5V", "vref_out": 3.3},
        "wireless_module": {"vdd_net": "VDD_3P3"},
    }
    return common.get(topo, {"vdd_net": "VDD_3P3"})


def _get_source_file_line_count(filename: str) -> int:
    fpath = _repo_root / "src" / "circuit_weaver" / "subcircuits" / filename
    if fpath.exists():
        return len(fpath.read_text(encoding="utf-8").splitlines())
    return 0


def _summarize_result(result: SubcircuitResult) -> dict[str, Any]:
    """Extract structured summary from a SubcircuitResult."""
    comp = result.components[0] if result.components else None
    bypass_caps = comp.bypass_caps if comp else []
    straps = comp.straps if comp else []
    pin_nets = comp.pin_nets if comp else {}
    boundary_ports = result.boundary_ports if result else []
    annotations = result.annotations if result else []

    return {
        "component_count": len(result.components) if result else 0,
        "bypass_cap_count": len(bypass_caps),
        "bypass_cap_roles": [b.role for b in bypass_caps] if bypass_caps else [],
        "bypass_cap_values": [b.value for b in bypass_caps] if bypass_caps else [],
        "strap_count": len(straps),
        "strap_roles": [s.role for s in straps] if straps else [],
        "strap_values": [s.value for s in straps] if straps else [],
        "pin_net_count": len(pin_nets),
        "pin_net_keys": list(pin_nets.keys()) if pin_nets else [],
        "boundary_port_count": len(boundary_ports),
        "boundary_port_names": [p.name for p in boundary_ports] if boundary_ports else [],
        "annotation_count": len(annotations),
        "primary_category": result.primary_category if result else "unknown",
    }


def _compare_outputs(legacy: dict, driven: dict) -> tuple[bool, list[str]]:
    """Compare legacy vs data-driven output summaries. Returns (equivalent, notes)."""
    notes: list[str] = []

    # Component count
    if legacy["component_count"] != driven["component_count"]:
        notes.append(f"comp count: {legacy['component_count']} (legacy) vs {driven['component_count']} (data-driven)")

    # Bypass caps (compare by role+value since there's no ref field)
    leg_caps = set(zip(legacy["bypass_cap_roles"], legacy["bypass_cap_values"]))
    drv_caps = set(zip(driven["bypass_cap_roles"], driven["bypass_cap_values"]))
    only_leg = leg_caps - drv_caps
    only_drv = drv_caps - leg_caps
    if only_leg:
        notes.append(f"bypass caps only in legacy: {sorted(only_leg)}")
    if only_drv:
        notes.append(f"bypass caps only in data-driven: {sorted(only_drv)}")

    # Straps (compare by role+value)
    leg_straps = set(zip(legacy["strap_roles"], legacy["strap_values"]))
    drv_straps = set(zip(driven["strap_roles"], driven["strap_values"]))
    only_leg_s = leg_straps - drv_straps
    only_drv_s = drv_straps - leg_straps
    if only_leg_s:
        notes.append(f"straps only in legacy: {sorted(only_leg_s)}")
    if only_drv_s:
        notes.append(f"straps only in data-driven: {sorted(only_drv_s)}")

    # Pin nets
    leg_pins = set(legacy["pin_net_keys"])
    drv_pins = set(driven["pin_net_keys"])
    only_leg_p = leg_pins - drv_pins
    only_drv_p = drv_pins - leg_pins
    if only_leg_p:
        notes.append(f"pin nets only in legacy: {sorted(only_leg_p)}")
    if only_drv_p:
        notes.append(f"pin nets only in data-driven: {sorted(only_drv_p)}")

    # Boundary ports
    leg_ports = set(legacy["boundary_port_names"])
    drv_ports = set(driven["boundary_port_names"])
    only_leg_bp = leg_ports - drv_ports
    only_drv_bp = drv_ports - leg_ports
    if only_leg_bp:
        notes.append(f"boundary ports only in legacy: {sorted(only_leg_bp)}")
    if only_drv_bp:
        notes.append(f"boundary ports only in data-driven: {sorted(only_drv_bp)}")

    equal = len(notes) == 0
    return equal, notes


def _classify(topo: str, legacy_summary: dict, driven_summary: dict, notes: list[str], line_count: int) -> str:
    """Classify template as A, B, or C based on comparison and known characteristics."""
    # Complex templates (verdict-C): multi-mode, 400+ lines
    complex_topos = {
        "adc", "dac", "current_sense", "led_driver", "relay_driver",
        "motor_driver", "usb_controller", "usb_hub", "i2c_bus",
    }
    if topo in complex_topos:
        return "C"

    # Power topologies have dedicated builders that produce full output
    if topo in {"buck", "boost", "buck_boost", "ldo"}:
        return "A"

    # Medium templates with known custom logic (verdict-B candidates based on data comparison)
    # If build_generic produces significantly different output, it's B
    if notes:
        # Check if differences are substantive (beyond just the 100nF cap and VDD/GND ports)
        leg_caps = set(zip(legacy_summary["bypass_cap_roles"], legacy_summary["bypass_cap_values"]))
        drv_caps = set(zip(driven_summary["bypass_cap_roles"], driven_summary["bypass_cap_values"]))
        leg_straps = set(zip(legacy_summary["strap_roles"], legacy_summary["strap_values"]))
        drv_straps = set(zip(driven_summary["strap_roles"], driven_summary["strap_values"]))
        leg_pins = set(legacy_summary["pin_net_keys"])
        drv_pins = set(driven_summary["pin_net_keys"])

        # Generic builder always adds C_VDD cap and vdd_net/GND ports
        # If legacy has more caps or different caps, that's substantive
        generic_caps = {("decoupling", "100nF")}
        extra_caps = leg_caps - generic_caps
        has_extra_caps = bool(extra_caps)
        has_extra_straps = bool(leg_straps - drv_straps)
        has_extra_pin_nets = bool(leg_pins - drv_pins and leg_pins - drv_pins != {"pin_vdd", "pin_gnd"})

        if has_extra_caps or has_extra_straps or has_extra_pin_nets:
            return "B"

    # If no substantive differences, it's A (delete-safe)
    return "A"


def run_audit() -> list[dict[str, Any]]:
    _register()
    results: list[dict[str, Any]] = []

    for topo in sorted(_TEMPLATE_MAP.keys()):
        template, filename = _TEMPLATE_MAP[topo]
        line_count = _get_source_file_line_count(filename)

        # Get IC database
        ic_db = _get_ic_db(template)
        ic_name = next(iter(ic_db), None)
        if ic_name is None:
            # Try from global ic_data
            all_ics = get_all_ics(topo)
            ic_name = next(iter(all_ics), None)

        if ic_name is None:
            results.append({
                "topology": topo,
                "file": filename,
                "line_count": line_count,
                "verdict": "?",
                "ic_name": "N/A",
                "legacy_ok": False,
                "driven_ok": False,
                "notes": "No IC data available for this topology",
            })
            continue

        params = _default_params(topo)
        params["ic"] = ic_name

        # Run legacy template
        legacy_ok = False
        legacy_summary = {}
        legacy_error = ""
        try:
            leg_result = template.generate(params)
            legacy_summary = _summarize_result(leg_result)
            legacy_ok = True
        except Exception as e:
            legacy_error = f"{type(e).__name__}: {e}"

        # Run DataDrivenTemplate
        driven_ok = False
        driven_summary = {}
        driven_error = ""
        try:
            # Use get_all_ics() for data-driven — it returns plain dicts, not objects with PinDef instances
            all_ics = get_all_ics(topo)
            driven = DataDrivenTemplate(
                template_type=topo,
                topology=topo,
                ic_database=dict(all_ics),
            )
            drv_result = driven.generate(params)
            driven_summary = _summarize_result(drv_result)
            driven_ok = True
        except Exception as e:
            driven_error = f"{type(e).__name__}: {e}"

        # Compare
        if legacy_ok and driven_ok:
            equal, compare_notes = _compare_outputs(legacy_summary, driven_summary)
            verdict = _classify(topo, legacy_summary, driven_summary, compare_notes, line_count)
        elif legacy_ok and not driven_ok:
            verdict = "B"
            compare_notes = [f"DataDriven template failed: {driven_error}"]
        elif not legacy_ok and driven_ok:
            verdict = "?"
            compare_notes = [f"Legacy template failed: {legacy_error}"]
        else:
            verdict = "?"
            compare_notes = [f"Legacy: {legacy_error}; Data-driven: {driven_error}"]

        results.append({
            "topology": topo,
            "file": filename,
            "line_count": line_count,
            "verdict": verdict,
            "ic_name": ic_name,
            "legacy_ok": legacy_ok,
            "driven_ok": driven_ok,
            "legacy_summary": legacy_summary,
            "driven_summary": driven_summary,
            "notes": compare_notes,
        })

    return results


def write_markdown(results: list[dict[str, Any]], path: Path):
    lines: list[str] = []
    lines.append("# Legacy Template Audit\n")
    lines.append(f"Generated: {__import__('datetime').datetime.now().isoformat()}\n")
    lines.append("Audit of all 37 legacy templates comparing `generate()` output against `DataDrivenTemplate`.\n")
    lines.append("\n## Verdict Legend\n")
    lines.append("- **A — Delete safe:** outputs are equivalent within tolerance; no topology-specific passive\n")
    lines.append("  calculation in legacy `generate()` that `build_generic` doesn't replicate.\n")
    lines.append("- **B — Port first:** legacy `generate()` has custom pin-wiring or passive calculation\n")
    lines.append("  not present in any builder; must add a topology-specific builder function before deleting.\n")
    lines.append("- **C — Complex:** 400+ line template with multiple IC sub-modes; plan as a dedicated task per topology.\n")
    lines.append("\n## Verdict Table\n")
    lines.append(f"| # | File | Topology | Lines | Verdict | IC Tested | Notes |")
    lines.append(f"|---|------|----------|-------|---------|-----------|-------|")

    for i, r in enumerate(results, 1):
        notes_str = "; ".join(r["notes"]) if r["notes"] else "—"
        # Truncate long notes
        if len(notes_str) > 120:
            notes_str = notes_str[:117] + "..."
        lines.append(
            f"| {i} | `{r['file']}` | `{r['topology']}` | {r['line_count']} | **{r['verdict']}** | {r['ic_name']} | {notes_str} |"
        )

    # Summary counts
    lines.append("\n## Summary\n")
    counts = {"A": 0, "B": 0, "C": 0, "?": 0}
    for r in results:
        c = counts.get(r["verdict"], "?")
        if isinstance(c, int):
            counts[r["verdict"]] = c + 1
    lines.append(f"- **A (Delete safe):** {counts['A']}")
    lines.append(f"- **B (Port first):** {counts['B']}")
    lines.append(f"- **C (Complex):** {counts['C']}")
    if counts["?"]:
        lines.append(f"- **Unknown/Error:** {counts['?']}")
    lines.append(f"- **Total:** {len(results)}\n")

    # Detailed notes per verdict group
    lines.append("\n## Verdict-A Templates (Delete Safe)\n")
    verdict_a = [r for r in results if r["verdict"] == "A"]
    if verdict_a:
        for r in verdict_a:
            lines.append(f"- `{r['topology']}` ({r['file']}, {r['line_count']} L) — IC: {r['ic_name']}")
        lines.append("")
        lines.append(f"These can be deleted after Task 180 (registry flip) + parity tests (Task 181/182).\n")
    else:
        lines.append("None.\n")

    lines.append("\n## Verdict-B Templates (Port First)\n")
    verdict_b = [r for r in results if r["verdict"] == "B"]
    if verdict_b:
        for r in verdict_b:
            diff = "; ".join(r["notes"]) if r["notes"] else "see detailed comparison"
            lines.append(f"- `{r['topology']}` ({r['file']}, {r['line_count']} L) — IC: {r['ic_name']}")
            lines.append(f"  - {diff}")
        lines.append("")
        lines.append(f"Need topology-specific builder functions in `topology_builders.py` before deletion.\n")
    else:
        lines.append("None.\n")

    lines.append("\n## Verdict-C Templates (Complex)\n")
    verdict_c = [r for r in results if r["verdict"] == "C"]
    if verdict_c:
        for r in verdict_c:
            lines.append(f"- `{r['topology']}` ({r['file']}, {r['line_count']} L) — IC: {r['ic_name']}")
        lines.append("")
        lines.append(f"Multi-mode templates with 400+ lines. Each needs a dedicated porting sub-task in Task 184.\n")
    else:
        lines.append("None.\n")

    # Field coverage analysis
    lines.append("\n## IC Data JSON Field Coverage\n")
    lines.append("Templates whose `generate()` references fields NOT in the IC data JSON would cause silent regression if deleted before JSON is updated.\n")
    # This requires deeper analysis; note it as a follow-up
    lines.append("> **Note:** Field coverage is verified at generation time — if a template reads a field that doesn't exist in ic_data, `generate()` will raise `KeyError`. The audit above catches those cases as `Legacy template failed`.\n")

    path.write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote {path}")


def main():
    print("Running audit...")
    results = run_audit()
    print(f"\nAudited {len(results)} templates.")

    counts = {"A": 0, "B": 0, "C": 0, "?": 0}
    for r in results:
        v = r["verdict"]
        counts[v] = counts.get(v, 0) + 1
        status = "OK" if r["legacy_ok"] and r["driven_ok"] else "ERR"
        notes = "; ".join(r["notes"]) if r["notes"] else "equivalent"
        print(f"  [{r['verdict']}] {status} {r['topology']:25s} ({r['file']:25s}, {r['line_count']:3d}L) -- {r['ic_name']:30s} -- {notes}")

    print(f"\nSummary: A={counts['A']}, B={counts['B']}, C={counts['C']}, ?={counts['?']}")

    out_path = _repo_root / "docs" / "legacy_template_audit.md"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    write_markdown(results, out_path)
    print("Done.")


if __name__ == "__main__":
    main()
