"""Subcircuit templates — reusable parametric circuit blocks.

Templates describe circuit *intent* (buck converter at 3.3V/2A) and produce
fully-wired ComponentDefs with auto-calculated passive values.

Two template sources:
  - Programmatic: Python class computes components from equations
  - KiCad import: parse a .kicad_sch snippet, replace placeholder values

Both produce SubcircuitResult with components, local wires, boundary labels.
"""

from .base import (
    SubcircuitRegistry as SubcircuitRegistry,
)
from .base import (
    SubcircuitResult as SubcircuitResult,
)
from .base import (
    SubcircuitTemplate as SubcircuitTemplate,
)
from .base import (
    snap_to_e24 as snap_to_e24,
)
from .base import (
    snap_to_e96 as snap_to_e96,
)
