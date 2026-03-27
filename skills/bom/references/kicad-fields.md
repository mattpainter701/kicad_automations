# KiCad Symbol Properties Reference

## Standard Fields

| Field | Description | Example |
|-------|-------------|---------|
| `Reference` | Designator (auto) | `C1`, `U3`, `R5` |
| `Value` | Component value | `100nF`, `ESP32-S3-WROOM-1` |
| `Footprint` | Library:footprint | `Capacitor_SMD:C_0402_1005Metric` |
| `Datasheet` | URL to datasheet | `https://...` |
| `Description` | Part description | `100nF 16V X7R 0402 MLCC` |

## Custom BOM Fields

| Field | Purpose | When | Example |
|-------|---------|------|---------|
| `MPN` | Manufacturer Part Number | Always | `GRM155R71C104KA88D` |
| `Manufacturer` | Part manufacturer | Always | `Murata` |
| `DigiKey` | DigiKey PN — primary prototype source | Prototype | `490-10698-1-ND` |
| `Mouser` | Mouser PN — secondary prototype source | Prototype | `81-GRM155R71C104KA8D` |
| `LCSC` | LCSC PN — production assembly source | Production | `C14663` |
| `AltMPN` | Alternate/second-source MPN | Optional | `CL05B104KO5NNNC` |

## Field Name Aliases

Projects use inconsistent field names. The analyzer recognizes all common variants:

| Canonical | Also Recognized As |
|---|---|
| `MPN` | `Manufacturer Part Number`, `Manufacturer_Part_Number`, `Manufacturer Part #`, `PartNumber`, `Part Number`, `Mfr_No`, `ManufacturerPartNumber` |
| `Manufacturer` | `Manufacturer_Name`, `Mfr`, `MFR` |
| `DigiKey` | `Digi-Key Part Number`, `Digi-Key_PN`, `DigiKey Part`, `DigiKey_Part_Number`, `DK` |
| `Mouser` | `Mouser Part Number`, `Mouser Part`, `Mouser_PN`, `Mouser PN` |
| `LCSC` | `LCSC Part #`, `LCSC Part Number`, `LCSCStockCode`, `JLCPCB`, `JLCPCB Part`, `JLC` |
| `element14` | `Newark`, `Newark Part Number`, `Newark_PN`, `Farnell`, `Farnell_PN`, `element14_PN` |

When writing new fields, use the canonical names for consistency. When a project already has a convention (e.g., `Digi-Key_PN`), respect it.

## S-expression Format

Custom fields in `.kicad_sch` files:

```
(property "MPN" "GRM155R71C104KA88D"
    (at 0 0 0)
    (effects (font (size 1.27 1.27)) (hide yes))
)
```

## Adding/Editing Properties in KiCad

- **Single symbol**: Double-click or E > "+" to add field
- **Bulk editing**: Tools > Edit Symbol Fields (spreadsheet view, supports CSV export/import)
- **Field Name Templates** (KiCad 9+): Schematic Setup > Field Name Templates — pre-define MPN, Manufacturer, etc.

## Part Number Patterns

- **MPN is the universal key** — cross-references across all distributors
- **DigiKey PNs** end in `-ND` (e.g., `311-10.0KCRCT-ND`)
- **Mouser PNs** have numeric prefixes (e.g., `81-GRM155R71C104KA8D`)
- **LCSC PNs** are `Cxxxxx` (e.g., `C14663`)
- **Newark/Farnell PNs** are alphanumeric SKUs (e.g., `94AK6874`)
- Any identifier is useful — even a single distributor PN can be used to find the MPN and other PNs
- Parts with no identifiers need manual enrichment before datasheet sync or ordering

For detailed analysis of part number conventions across 56+ real-world projects, see `part-number-conventions.md`.
