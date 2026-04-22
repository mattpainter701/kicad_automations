# Tracing Net Connectivity in Raw `.kicad_sch` Files

KiCad schematics don't store explicit netlists — connectivity is implicit via coordinate matching. To verify a connection between two pins:

## CRITICAL: Y-axis inversion

**This is the single most common source of errors when tracing nets programmatically.** KiCad symbol library coordinates use math convention (Y-up), but schematic placement coordinates use screen convention (Y-down). You MUST subtract pin Y from symbol Y:

```
absolute = (symbol_X + pin_X, symbol_Y - pin_Y)
```

**Getting this wrong inverts the entire pin map** — pin 1 appears where pin N should be, and vice versa. Every "missing connection" or "wrong pin" finding that comes from coordinate math should be double-checked for this error. If a script reports that a pin is unconnected but the user says the schematic is correct, the Y-axis transform is almost certainly wrong.

## Step 1: Find pin positions in the symbol library definition

Each symbol has pins defined with relative offsets in the `lib_symbols` section:
```
(symbol "BSS84_1_1"
  (pin input line (at -5.08 0 0) ... (number "1"))      ; Gate
  (pin passive line (at 2.54 5.08 270) ... (number "3")) ; Drain
  (pin passive line (at 2.54 -5.08 90) ... (number "2")) ; Source
)
```

## Step 2: Calculate absolute pin positions

Apply the symbol's placement transform: `(at X Y ANGLE)`.

**No rotation (0 deg):**
- Pin at relative (px, py) -> absolute **(X + px, Y - py)**
- The Y subtraction is mandatory — symbol pin coordinates use math convention (up = positive Y), while schematic coordinates use screen convention (down = positive Y).

**With rotation:** Apply rotation matrix to pin offset BEFORE the Y inversion, then add to symbol position.
- 90 deg CW: (px, py) -> (py, -px) -> absolute (X + py, Y - (-px)) = (X + py, Y + px)
- 180 deg: (px, py) -> (-px, -py) -> absolute (X + (-px), Y - (-py)) = (X - px, Y + py)
- 270 deg CW: (px, py) -> (-py, px) -> absolute (X + (-py), Y - px) = (X - py, Y - px)

Example: Symbol at (161.29, 176.53), pin at relative (-5.08, 0), no rotation:
- Absolute: (161.29 + (-5.08), 176.53 - 0) = (156.21, 176.53)

Example: Resistor at (152.4, 176.53) rotated 90 deg, pin 1 at relative (0, 3.81):
- Rotated offset: (3.81, 0) -> absolute: (152.4 + 3.81, 176.53 - 0) = (156.21, 176.53)
- Same point as the gate pin above -> directly connected!

## Important: Multi-sided IC symbols have pins on different sides at the same Y-coordinate

Large IC symbols (e.g., ESP32 modules) have pins on the left **and** right sides. Two different pins can share the same Y-coordinate but have very different X-coordinates. A `no_connect` or wire at `(91.44, 77.47)` is NOT the same pin as a wire endpoint at `(60.96, 77.47)` — they are on opposite sides of the symbol.

**Always verify BOTH X and Y** when matching coordinates. To determine which side a pin exits from:
1. Find the pin's relative offset in the `lib_symbols` definition — negative X = left side, positive X = right side
2. Apply the symbol's placement transform to get the absolute position
3. Match against wires/labels/no_connects using the **exact** (X, Y) pair

Do not assume a pin exits on a particular side based on the pin name or number alone.

## Step 3: Trace wires from pin positions

Search for `(wire (pts (xy X1 Y1) (xy X2 Y2)))` where one endpoint matches the pin position. Follow the wire chain endpoint-to-endpoint.

**KiCad 9 wire format note:** The `(wire` keyword, `(pts` keyword, and coordinate data may be on separate lines:
```
(wire
    (pts
        (xy 41.91 77.47) (xy 60.96 77.47)
    )
```
When extracting wires programmatically, search up to 4-5 lines ahead from `(wire` to find the `(xy ...)` coordinates.

## Step 4: Identify net names at wire endpoints

Look for:
- **Power symbols**: `(lib_id "power:GND")` or `(lib_id "power:+BATT")` placed at a wire endpoint — the symbol's Value property is the net name
- **Labels**: `(label "NET_NAME" (at X Y ...))` at a wire endpoint
- **Global labels**: `(global_label "NET_NAME" (at X Y ...))` for cross-sheet nets
- **Junctions**: `(junction (at X Y))` marks where crossing wires connect
- **Other component pins**: Another symbol's pin at the same coordinate

**Global label parsing note (KiCad 9):** The `(at ...)` is NOT on the line immediately after `(global_label "...")`. There is a `(shape ...)` line in between:
```
(global_label "EN_5V"
    (shape input)
    (at 43.18 128.27 180)
```
When extracting labels, search 2-3 lines ahead for the `(at ...)` coordinates, not just the next line.

**Labels connect via wires, not just at pin endpoints.** A global label is typically placed at the far end of a short wire stub extending from the pin. To find which label connects to which pin, you must trace the wire chain from the pin endpoint to the label position — checking only the exact pin coordinate will miss most connections.

## Step 5: Verify with junctions

If a wire passes through a point where another wire starts, they only connect if there's a `(junction ...)` at that point, OR if the wire endpoint exactly matches.

## Common False Positive Patterns

### Reference designator reuse
When a component is removed from a schematic (e.g., R13 was a GPIO pullup), its reference designator may be reused for a completely different component (e.g., R13 becomes a gate pulldown for a FET). Do not assume a reference designator has the same function across schematic revisions. Always check what the component actually connects to in the current schematic.

### Connector naming conventions
Not all "programming" connectors are JTAG. A 2x3 header (J2) with TX, RX, GND, 3V3, EN, and BOOT pins is a **serial programming header** (UART), not a JTAG header. JTAG requires TCK, TMS, TDI, TDO signals. Check the actual pin assignments before labeling a connector.

## Complete Example

To verify Q4 (P-FET) gate connects to R13 -> GND:
1. Q4 at (161.29, 176.53), BSS84 Gate pin at (-5.08, 0) -> absolute **(156.21, 176.53)**
2. R13 at (152.4, 176.53) rotated 90 deg, Pin 1 at (0, 3.81) -> rotated (3.81, 0) -> absolute **(156.21, 176.53)** — same point, direct connection
3. R13 Pin 2 at (0, -3.81) -> rotated (-3.81, 0) -> absolute **(148.59, 176.53)**
4. Wire from (147.32, 176.53) to (148.59, 176.53) connects to R13 Pin 2
5. Junction at (147.32, 176.53), wire to (147.32, 177.8)
6. `power:GND` symbol at (147.32, 177.8) -> **GND net**
