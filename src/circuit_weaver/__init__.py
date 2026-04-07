"""Circuit Weaver.

Programmatic circuit design, validation, and KiCad artifact generation.
"""

from .enclosure_designer import generate_enclosure_scad, render_enclosure_stl

__all__ = ["__version__", "generate_enclosure_scad", "render_enclosure_stl"]

__version__ = "0.13.0a1"
