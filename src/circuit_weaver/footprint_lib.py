"""Local KiCad footprint library lookup.

Circuit Weaver stores footprint bindings as KiCad library references such as
``Package_TO_SOT_SMD:SC-70-5``.  This module checks whether those references
exist in the user's local KiCad footprint libraries before a design is treated
as fabrication-ready.
"""

from __future__ import annotations

import json
import os
import platform
from importlib import resources
from pathlib import Path
from urllib.parse import quote

_KICAD_FOOTPRINT_PATHS = {
    "Windows": [
        Path("C:/Program Files/KiCad/10.0/share/kicad/footprints"),
        Path("C:/Program Files/KiCad/9.0/share/kicad/footprints"),
        Path("C:/Program Files/KiCad/8.0/share/kicad/footprints"),
    ],
    "Linux": [
        Path("/usr/share/kicad/footprints"),
        Path("/usr/local/share/kicad/footprints"),
    ],
    "Darwin": [
        Path("/Applications/KiCad/KiCad.app/Contents/SharedSupport/footprints"),
        Path("/usr/local/share/kicad/footprints"),
    ],
}


class KiCadFootprintLibrary:
    """Resolve KiCad footprint references against local `.pretty` libraries."""

    def __init__(self, root: str | Path | None = None) -> None:
        self._roots = self._default_roots(root)

    @staticmethod
    def _default_roots(root: str | Path | None) -> list[Path]:
        roots: list[Path] = []
        if root:
            roots.append(Path(root))
        env = os.environ.get("KICAD_FOOTPRINT_DIR") or os.environ.get("KICAD8_FOOTPRINT_DIR")
        if env:
            roots.append(Path(env))
        roots.extend(_KICAD_FOOTPRINT_PATHS.get(platform.system(), []))
        return [p for p in roots if p.is_dir()]

    @property
    def roots(self) -> list[Path]:
        return list(self._roots)

    def footprint_exists(self, footprint: str) -> bool:
        """Return True when ``Lib:Footprint`` exists locally."""
        if not footprint or ":" not in footprint:
            return False
        lib, name = footprint.split(":", 1)
        if not lib or not name:
            return False
        rel = Path(f"{lib}.pretty") / f"{name}.kicad_mod"
        return any((root / rel).is_file() for root in self._roots)

    def find(self, query: str) -> list[str]:
        """Find local footprint refs whose name contains ``query``."""
        q = query.lower().strip()
        if not q:
            return []
        matches: list[str] = []
        for root in self._roots:
            for pretty in sorted(root.glob("*.pretty")):
                for mod in sorted(pretty.glob("*.kicad_mod")):
                    if q in mod.stem.lower():
                        matches.append(f"{pretty.stem}:{mod.stem}")
        return matches


def official_kicad_footprint_url(footprint: str) -> str:
    """Return the official KiCad footprint-library browser URL for a ref."""
    if not footprint or ":" not in footprint:
        return "https://gitlab.com/kicad/libraries/kicad-footprints"
    lib, name = footprint.split(":", 1)
    lib_path = quote(f"{lib}.pretty", safe="")
    mod_path = quote(f"{name}.kicad_mod", safe="")
    return f"https://gitlab.com/kicad/libraries/kicad-footprints/-/blob/master/{lib_path}/{mod_path}"


def curated_footprint_alternatives(mpn: str, fp_lib: KiCadFootprintLibrary | None = None) -> list[dict[str, str]]:
    """Return curated alternates that use available KiCad-backed footprints."""
    key = (mpn or "").strip().upper()
    if not key:
        return []
    try:
        raw = resources.files("circuit_weaver.ic_data").joinpath("alternates.json").read_text(encoding="utf-8")
        data = json.loads(raw)
    except (FileNotFoundError, json.JSONDecodeError, ModuleNotFoundError):
        return []

    candidates = data.get(key) or data.get(mpn) or []
    if not isinstance(candidates, list):
        return []

    out: list[dict[str, str]] = []
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        footprint = str(candidate.get("footprint", "")).strip()
        if fp_lib is not None and fp_lib.roots and not fp_lib.footprint_exists(footprint):
            continue
        out.append({
            "mpn": str(candidate.get("mpn", "")).strip(),
            "footprint": footprint,
            "reason": str(candidate.get("reason", "")).strip(),
        })
    return out


def custom_footprint_suggestion(mpn: str, footprint: str, fp_lib: KiCadFootprintLibrary) -> str:
    """Build an actionable suggestion for a missing/custom footprint."""
    alts = curated_footprint_alternatives(mpn, fp_lib)
    if alts:
        rendered = "; ".join(
            f"{alt['mpn']} ({alt['footprint']}) — {alt['reason']}"
            for alt in alts
            if alt.get("mpn") and alt.get("footprint")
        )
        if rendered:
            return (
                "Safer KiCad-footprint-backed alternatives available: "
                f"{rendered}. Keep {mpn} only in advanced/custom-footprint mode after importing and verifying "
                "a trusted vendor/project .pretty footprint."
            )
    return (
        f"No curated KiCad-footprint-backed alternate is known for {mpn or footprint}; "
        "treat this as advanced/custom-footprint mode and import/verify a trusted vendor or project .pretty "
        "footprint before fabrication."
    )
