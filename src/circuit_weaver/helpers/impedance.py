"""Generic controlled-impedance math helpers for PCB workflows."""

from __future__ import annotations

import math

GENERIC_6L_FR4_STACKUP = {
    "name": "generic_6layer_fr4",
    "total_mm": 1.6,
    "layers": [
        ("L1_F.Cu", "copper", 0.035, None, None, 1.0),
        ("PP_top", "prepreg", 0.10, 4.10, 0.02, None),
        ("L2_In1.Cu", "copper", 0.018, None, None, 0.5),
        ("Core_1", "core", 0.55, 4.30, 0.02, None),
        ("L3_In2.Cu", "copper", 0.018, None, None, 0.5),
        ("PP_mid", "prepreg", 0.12, 4.20, 0.02, None),
        ("L4_In3.Cu", "copper", 0.018, None, None, 0.5),
        ("Core_2", "core", 0.55, 4.30, 0.02, None),
        ("L5_In4.Cu", "copper", 0.018, None, None, 0.5),
        ("PP_bot", "prepreg", 0.10, 4.10, 0.02, None),
        ("L6_B.Cu", "copper", 0.035, None, None, 1.0),
    ],
}


def microstrip_z0(w_mm: float, h_mm: float, er: float, t_mm: float = 0.035) -> tuple[float, float]:
    """Microstrip impedance using Hammerstad-Jensen."""
    w = w_mm
    h = h_mm
    t = t_mm

    if t > 0 and h > 0:
        dw = (t / math.pi) * (1.0 + math.log(2.0 * h / t))
        we = w + dw
    else:
        we = w

    u = we / h
    a = (
        1.0
        + (1.0 / 49.0) * math.log((u**4 + (u / 52.0) ** 2) / (u**4 + 0.432))
        + (1.0 / 18.7) * math.log(1.0 + (u / 18.1) ** 3)
    )
    b = 0.564 * ((er - 0.9) / (er + 3.0)) ** 0.053
    er_eff = (er + 1.0) / 2.0 + (er - 1.0) / 2.0 * (1.0 + 10.0 / u) ** (-a * b)
    f_u = 6.0 + (2.0 * math.pi - 6.0) * math.exp(-((30.666 / u) ** 0.7528))
    z0 = (377.0 / (2.0 * math.pi * math.sqrt(er_eff))) * math.log(
        f_u / u + math.sqrt(1.0 + (2.0 / u) ** 2)
    )
    return z0, er_eff


def stripline_z0(
    w_mm: float,
    h1_mm: float,
    h2_mm: float,
    er: float,
    t_mm: float = 0.018,
) -> tuple[float, float]:
    """Offset stripline impedance using a Cohn/Wadell-style approximation."""
    h_eff = 2.0 * h1_mm * h2_mm / (h1_mm + h2_mm)
    if w_mm <= 0 or h_eff <= 0:
        return 0.0, er
    cf = w_mm / (2.0 * h_eff)
    if cf < 0.35:
        z0 = (60.0 / math.sqrt(er)) * math.log(4.0 * h_eff / (0.67 * (0.8 * w_mm + t_mm)))
    else:
        z0 = (
            (377.0 / (2.0 * math.sqrt(er)))
            / (
                cf
                + (2.0 / math.pi)
                * math.log((2.0 * cf + 1.0) / (2.0 * cf - 1.0) if cf > 0.5 else 10.0)
            )
            if cf > 0.5
            else (60.0 / math.sqrt(er)) * math.log(4.0 * h_eff / (0.67 * (0.8 * w_mm + t_mm)))
        )
    return z0, er


def differential_microstrip_z0(
    w_mm: float,
    s_mm: float,
    h_mm: float,
    er: float,
    t_mm: float = 0.035,
) -> tuple[float, float, float, float]:
    """Edge-coupled differential microstrip approximation."""
    z0_single, er_eff = microstrip_z0(w_mm, h_mm, er, t_mm)
    g = s_mm / h_mm
    k_coup = math.exp(-2.0 * g) if g < 5.0 else 0.0
    z_odd = z0_single * (1.0 - 0.48 * k_coup * math.sqrt(er_eff))
    z_even = z0_single * (1.0 + 0.48 * k_coup * math.sqrt(er_eff))
    z_diff = 2.0 * z_odd
    return z_diff, z_odd, z_even, er_eff


def find_width_for_z0(
    target_z0: float,
    h_mm: float,
    er: float,
    t_mm: float = 0.035,
    w_min: float = 0.05,
    w_max: float = 2.0,
    tol: float = 0.01,
) -> float:
    """Binary-search a microstrip width that achieves the target impedance."""
    lo, hi = w_min, w_max
    for _ in range(100):
        mid = (lo + hi) / 2.0
        z0, _ = microstrip_z0(mid, h_mm, er, t_mm)
        if abs(z0 - target_z0) < tol:
            return mid
        if z0 > target_z0:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2.0
