"""Circuit Weaver.

Programmatic circuit design, validation, and KiCad artifact generation.
"""

from .enclosure_designer import generate_enclosure_scad, render_enclosure_stl
from .kicad_placement_api import check_kicad_available, detect_kicad_version, update_board_placements

__all__ = [
    "__version__",
    "generate_enclosure_scad",
    "render_enclosure_stl",
    "check_kicad_available",
    "detect_kicad_version",
    "update_board_placements",
]

__version__ = "0.15.2"
