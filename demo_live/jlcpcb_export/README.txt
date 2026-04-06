JLCPCB PCB Assembly Upload Instructions
==================================================

Project: WiFi_Sensor_v1

Files Included:
  - bom_jlcpcb.csv        BOM for parts matching
  - cpl_jlcpcb.csv        Centroid/placement file
  - (gerbers/)            Gerber files (export separately from KiCad)

Upload Steps:
  1. Go to https://jlcpcb.com/quote
  2. Upload Gerber ZIP file
  3. Configure PCB: 2-layer, 1.6mm thickness, color, quantity
  4. Proceed to quote
  5. Enable 'PCB Assembly'
  6. Upload BOM file (bom_jlcpcb.csv)
  7. Upload CPL file (cpl_jlcpcb.csv)
  8. Review part matching and confirm

Notes:
  - Parts with empty LCSC Part# must be sourced separately
  - JLCPCB basic parts (no setup fee): ~700 common components
  - Extended parts (setup fee $3 each): remaining components
  - Verify all part matches before confirming order
