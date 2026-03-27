---
name: vivado
description: >
  Xilinx/AMD Vivado FPGA build workflow -- batch-mode TCL scripting, ADI HDL
  reference design integration, Zynq-7000/MPSoC block design, IP builds,
  synthesis, implementation, and bitstream generation. Use for any Zynq or
  UltraScale+ design that incorporates ADI transceivers or follows the ADI
  HDL reference design pattern.
---

## Environment Setup

| Item | Notes |
|-|-|
| Vivado | AMD Vivado 2024.x or 2025.x — batch mode preferred for CI |
| ADI HDL | Clone from `https://github.com/analogdevicesinc/hdl` |
| Version mismatch | Set `ADI_IGNORE_VERSION_CHECK=1` for minor version mismatches |
| Windows paths | Use forward slashes in TCL; backslashes cause parser errors |
| Linux | Preferred for CI builds; AMD tools are more stable on Linux |

```bash
# Vivado batch mode (Linux)
vivado -mode batch -source scripts/system_project.tcl 2>&1 | tee build.log

# Vivado batch mode (Windows)
"C:/AMD/Vivado/2025.1/bin/vivado.bat" -mode batch -source scripts/system_project.tcl

# Always run from build/ directory (ADI infra assumes this)
cd fpga/build/
export ADI_IGNORE_VERSION_CHECK=1
vivado -mode batch -source ../scripts/system_project.tcl
```

## ADI HDL Reference Design Pattern

ADI's open-source HDL repo provides reference designs and reusable IP for
AD9361, ADRV9002, ADRV9006, AD9371, AD9375, AD9364, ADAS1000, and many others.
The infrastructure (TCL procs, AXI IP cores, DMA, CDC utilities) is the same
across all parts.

### Repository Layout (ADI HDL)

```
hdl/
  library/          -- Reusable IP cores (axi_ad9361, axi_adrv9001, axi_dmac, etc.)
  projects/         -- Reference designs (one per eval board)
  scripts/          -- adi_board.tcl, adi_project.tcl (key infrastructure)
```

### Key TCL Procedures

```tcl
# In adi_board.tcl / adi_project.tcl:
adi_project_create <name> 0 {} {<device_part>}     # Create project for device
ad_ip_instance <type> <name>                        # Instantiate IP in block design
ad_ip_parameter <name> <param> <value>              # Set IP parameter
ad_connect <a> <b>                                  # Connect pins/nets/interfaces
ad_cpu_interconnect <addr> <periph>                 # Add to GP AXI interconnect
ad_mem_hp_interconnect <clk> <periph>               # Add to HP memory interconnect
ad_cpu_interrupt <ps-N> <mb-N> <irq>               # Connect interrupt
```

### Build a Custom Project Using ADI IPs

```
1. Clone ADI HDL: git clone https://github.com/analogdevicesinc/hdl
2. Create project directory: fpga/scripts/
3. Write system_project.tcl — calls adi_project_create, sources system_bd.tcl
4. Write system_bd.tcl — block design: PS7/PSU + ADI IPs + DMA + interconnects
5. Write system_top.v — top-level Verilog instantiating the BD wrapper + LVDS/CMOS IO
6. Write system_constr.xdc — pin constraints + timing
7. Build: cd build/ && vivado -mode batch -source ../scripts/system_project.tcl
```

### Required IP Builds (one-time per ADI HDL clone)

Build IP libraries before referencing them in a project. On Linux use `make`:

```bash
# Build all IPs (slow, ~1-2 hours)
cd hdl/library && make

# Build specific IPs (faster — build only what you use)
cd hdl/library/axi_dmac && vivado -mode batch -source axi_dmac_ip.tcl
cd hdl/library/util_cdc  && vivado -mode batch -source util_cdc_ip.tcl
cd hdl/library/axi_ad9361 && vivado -mode batch -source axi_ad9361_ip.tcl
```

On Windows `make` is unavailable — build IPs individually:

```bash
# Windows: build each IP with vivado batch
for ip in axi_adrv9001 axi_dmac util_cdc util_cpack2 util_upack2 axi_sysid sysid_rom util_axis_fifo; do
  vivado.bat -mode batch -source hdl/library/${ip}/${ip}_ip.tcl
done
```

## Zynq-7000 (PS7) Block Design

### PS7 Clock Domains

```tcl
# Standard 3-clock setup (matches ADI reference designs)
ad_ip_parameter sys_ps7 CONFIG.PCW_FPGA0_PERIPHERAL_FREQMHZ 100  ;# sys_cpu_clk
ad_ip_parameter sys_ps7 CONFIG.PCW_FPGA1_PERIPHERAL_FREQMHZ 200  ;# sys_dma_clk
ad_ip_parameter sys_ps7 CONFIG.PCW_FPGA2_PERIPHERAL_FREQMHZ 200  ;# sys_iodelay_clk

# Connect clocks (must be named bd_nets, not bd_pins, for ad_mem_hp_interconnect)
ad_connect sys_cpu_clk  sys_ps7/FCLK_CLK0
ad_connect sys_dma_clk  sys_ps7/FCLK_CLK1
ad_connect sys_iodelay_clk sys_ps7/FCLK_CLK2
set sys_cpu_clk    [get_bd_nets sys_cpu_clk]
set sys_dma_clk    [get_bd_nets sys_dma_clk]
set sys_iodelay_clk [get_bd_nets sys_iodelay_clk]
```

### MIO Peripheral Assignment

MIO ranges are fixed per peripheral — the Zynq-7000 TRM Table B.26 defines valid ranges.

| Peripheral | Valid MIO ranges |
|-|-|
| QSPI | 0..5 (single), 0..9 (dual) |
| SD0 | 16..21, 28..33, 40..45 (select via PCW_SD0_SD0_IO) |
| SD1 | 10..15, 22..27, 34..39, 46..51 |
| UART0 | 10..15, 18..19, 22..27, 30..31, 34..39, 46..51 |
| UART1 | 8..13, 16..17, 20..21, 24..29, 32..37, 40..45, 48..53 |
| I2C0 | 10..15, 22..27, 34..39, 46..51 (pairs: 10-11, 14-15, etc.) |
| I2C1 | 12..13, 16..17, 20..21, 24..25, 28..29, 32..33, 36..37, 40..41 |
| SPI0 | 16..21, 28..33, 40..45 |
| SPI1 | 10..15, 22..27, 34..39, 46..51 |
| GPIO | Any MIO not used by peripherals |

**Key rules:**
- Enable peripherals in TCL order: SD0 before SPI0 if they share valid ranges
- SPI on MIO = no EMIO ports needed; don't wire SPI ports in system_top.v
- UART must have TX+RX assigned to the same MIO range pair

### Interrupt Wiring

```tcl
# Pre-connect all interrupt concat inputs to GND before wiring peripherals
# (ad_cpu_interrupt does disconnect+reconnect — fails on floating inputs)
ad_connect GND xlconcat_0/In0
ad_connect GND xlconcat_0/In1
# ... repeat for all inputs
ad_cpu_interrupt ps-13 mb-13 axi_adrv9001/irq
ad_cpu_interrupt ps-12 mb-12 axi_adrv9001_rx1_dma/irq
```

## MPSoC / UltraScale+ (PSU)

Same ADI infrastructure, different IP name (`sys_psu` instead of `sys_ps7`),
HP ports become HPM ports, and interrupt numbering changes. The ADI reference
designs for ZCU102/ZCU104 show the pattern.

```tcl
# MPSoC uses PSU instead of PS7
ad_ip_instance zynq_ultra_ps_e sys_psu
ad_ip_parameter sys_psu CONFIG.PSU__USE__M_AXI_GP0 1
ad_ip_parameter sys_psu CONFIG.PSU__USE__S_AXI_HP0 1
```

## AXI Address Map

```tcl
# Assign base addresses for peripherals on GP0 (CPU-accessible)
# Standard ADI layout (customize as needed):
assign_bd_address -target_address_space sys_ps7/Data \
  [get_bd_addr_segs axi_ip_name/s_axi/reg0] -range 0x10000 -offset 0x44A00000
```

Typical ADI address ranges:
- `0x44A00000` — transceiver core (axi_ad9361, axi_adrv9001, etc.)
- `0x44A30000+` — DMA channels (4 × 0x10000 each for RX1, RX2, TX1, TX2)
- `0x45000000` — axi_sysid

## Build Artifacts

```
build/
  <project>.xpr           -- Vivado project file
  <project>.runs/
    synth_1/              -- Synthesis outputs
    impl_1/               -- Implementation outputs + bitstream
  <project>.sdk/          -- XSA + FSBL sources (post-implementation)
```

```bash
# Export hardware (XSA) for Vitis/PetaLinux
write_hw_platform -fixed -force -file system_top.xsa
```

## BOOT.bin Generation

```bash
# Generate FSBL from XSA
vitis -s build_fsbl.tcl   # or use Vitis GUI

# Package BOOT.bin (FSBL + bitstream + u-boot/app)
bootgen -image boot.bif -arch zynq -o BOOT.bin -w
```

`boot.bif` format:
```
the_ROM_image:
{
  [bootloader] fsbl.elf
  system_top.bit
  u-boot.elf
}
```

## Simulation (Vivado Simulator / ModelSim)

```tcl
# Add simulation sources
add_files -fileset sim_1 tb/tb_top.v

# Run behavioral simulation
set_property top tb_top [get_filesets sim_1]
launch_simulation -simset sim_1 -mode behavioral
```

For ADI IP simulation, use ADI's `hdl/testbenches/` directory which provides
self-checking testbenches for DMA, CDC, and transceiver data paths.

## ILA Debug Cores

```tcl
# Add ILA after synthesis to probe internal signals
create_debug_core u_ila_0 ila
set_property C_DATA_DEPTH 4096 [get_debug_cores u_ila_0]
set_property C_NUM_OF_PROBES 4 [get_debug_cores u_ila_0]
connect_debug_port u_ila_0/probe0 [get_nets {axi_data[7:0]}]
implement_debug_core
write_bitstream -force system_top.bit
```

## Common Gotchas

1. **DDR part number format:** Vivado uses a space before the speed grade: `MT41K256M16 HA-125` not `MT41K256M16HA-125`. Wrong format → DDR interface fails.
2. **Clock/reset must be named nets:** Use `set sys_cpu_clk [get_bd_nets sys_cpu_clk]` — using `get_bd_pins` breaks `ad_mem_hp_interconnect`.
3. **Interrupt concat inputs must pre-connect to GND:** `ad_cpu_interrupt` disconnects then reconnects — floating inputs cause TCL errors.
4. **PS7 DDR wrapper is always 32-bit:** DQ[31:0], DM[3:0], DQS[3:0] — even if the physical bus is 16-bit the Vivado wrapper adds both bytes.
5. **`flock` unavailable on Windows:** ADI Makefile uses it; build IPs individually with vivado batch on Windows.
6. **`adi_project_create` sources system_bd.tcl from CWD:** Put a thin wrapper in `build/` that sources `../scripts/system_bd.tcl` — do not source from the scripts/ dir directly.
7. **`ADI_IGNORE_VERSION_CHECK=1`:** Required when using a slightly newer Vivado than ADI targets — ADI validates exact version and errors out otherwise.
8. **SPI MIO ranges are fixed per peripheral:** Wrong range (e.g. SPI0 on MIO 10..15) → PS7 validation error at block design validation. Consult TRM Table B.26.
9. **IDELAYCTRL requires 200 MHz:** `sys_iodelay_clk` must be exactly 200 MHz — not 199 or 201. Drives LVDS capture IDELAY elements.
10. **Vivado 2025.x `EXCEPTION_ACCESS_VIOLATION`** after IP synthesis `report_utilization` — benign, checkpoint is written. Continue; retry uses cache.

## Post-Synthesis Checklist

- [ ] Synthesis: no critical warnings about undriven inputs or multi-driven nets
- [ ] Timing: `report_timing_summary` shows all paths met (WNS > 0, TNS = 0)
- [ ] Utilization: LUT/FF/BRAM/DSP within device limits with margin
- [ ] Pin assignments: all I/O assigned in XDC, no unplaced ports
- [ ] Bitstream: generated without errors
- [ ] XSA exported for SDK/Vitis/PetaLinux
