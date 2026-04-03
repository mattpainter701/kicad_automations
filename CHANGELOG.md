# Changelog

## [0.3.0] - TBD

### Sprint 2 — Template Expansion & DFM Quality

### Added

### Changed

### Fixed

### Tests

## [0.2.0] - TBD

### Sprint 1 — Robust KiCad Import Pipeline

### Added

### Changed

### Fixed

### Tests

## [0.1.0] - 2026-04-02

### Initial Release

### Added
- Circuit Weaver schematic generation engine
- 6 subcircuit templates: buck, ldo, clock, ethernet, usb_controller, usb_hub
- 22-component built-in registry with full pin/bypass/strap metadata
- KiCad 8/9/10 symbol library import (10,000+ parts via local install or GitLab)
- Multi-sheet hierarchical schematic generation with boundary net promotion
- Auto-placement engine with topology-aware motif renderers
- Transactional MVP workflow: validate, generate, apply-patch, diff, ingest-pcb-feedback
- PCB placement export and constraint feedback loop
- 3 sample circuits: usb_regulated_supply, led_power_indicator, iot_sensor_node
- Presentation parity: topology-local rendering for all support passives
- Review presentation profile (--presentation-profile review)
- Decoupling bank and strap ladder motif renderers
- 32 tests (bootstrap, helpers, presentation regression)
