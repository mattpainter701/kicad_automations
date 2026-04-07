# Contributing to Circuit Weaver

Thank you for your interest in contributing! This guide walks you through setting up your development environment, running tests, and submitting changes.

## Getting Started

### Prerequisites

- Python 3.10+
- Git
- pip (or your preferred Python package manager)

### Setup Development Environment

1. **Clone the repository:**
   ```bash
   git clone https://github.com/yourusername/circuit-weaver.git
   cd circuit-weaver
   ```

2. **Create a virtual environment:**
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. **Install in editable mode with dev dependencies:**
   ```bash
   pip install -e .[dev]
   ```

4. **Verify installation:**
   ```bash
   python -m pytest tests/ -q
   ```

## Development Workflow

### Branch Strategy

Create a feature branch from `main`:
```bash
git checkout -b feature/your-feature-name
```

### Coding Standards

- **Line length:** 120 characters (enforced by `ruff`)
- **String formatting:** f-strings (not `.format()` or `%`)
- **Imports:** Explicit imports only (no `from module import *`)
- **Type hints:** On all public functions
- **Path handling:** Use `pathlib.Path` (not `os.path`)

### Running Tests

```bash
# Run all tests
python -m pytest tests/ -q

# Run specific test file
python -m pytest tests/test_dispatcher.py -v

# Run with coverage
python -m pytest tests/ --cov=src/circuit_weaver
```

### Code Quality Checks

```bash
# Linting
python -m ruff check src/ tests/

# Fix formatting (auto)
python -m ruff format src/ tests/

# Type checking (if mypy installed)
python -m mypy --ignore-missing-imports src/
```

## Submitting Changes

### Commit Message Format

Follow conventional commits:
```
type: description (Task NNN)

Optional body with details.
```

**Types:** `feat`, `fix`, `refactor`, `test`, `docs`, `chore`, `perf`, `ci`

**Examples:**
```
feat: Add LDO template with auto-decoupling (Task 42)
fix: Validate component values against datasheet ratings (Task 55)
test: Add regression suite for SVG placement import (Task 93)
```

### Pre-Commit Checks

Before committing, run:
```bash
python -m pytest tests/ -q
python -m ruff check src/ tests/
```

### Creating a Pull Request

1. Push your branch to your fork
2. Open a PR against `main` with:
   - Clear title (under 70 chars)
   - Description of changes
   - Reference to related issues/tasks (`Task NNN`)
   - List of testing steps

## Project Structure

```
circuit-weaver/
├── src/circuit_weaver/
│   ├── __main__.py            # CLI entry point
│   ├── dispatcher.py                 # Core workflow (validate, generate, scaffold, etc.)
│   ├── design_ir.py           # Internal Design Representation (IR)
│   ├── validator.py           # Design validation logic
│   ├── generator.py           # KiCad artifact generation
│   ├── subcircuits/           # Template-based circuit blocks (LDO, buck, etc.)
│   ├── component_db.py        # Component metadata
│   ├── project_spec.py        # YAML/JSON spec parsing
│   └── skills/                # Global skills (circuit-weaver, bom, ee, etc.)
├── tests/
│   ├── test_dispatcher.py            # Core workflow tests
│   ├── test_presentation.py   # Component rendering tests
│   ├── test_import_pipeline.py # Spec import/patch tests
│   └── samples/               # Example designs for regression testing
├── docs/
│   ├── cli-reference.md       # Command-line interface docs
│   ├── api-reference.md       # Python API docs
│   ├── validation-codes.md    # Validation error reference
│   └── design-ir-schema.md    # YAML spec schema
├── pyproject.toml             # Project metadata & dependencies
├── TASKS.md                   # Sprint planning & task tracking
└── CHANGELOG.md               # Version history
```

## Key Modules

### `dispatcher.py` — Core Workflow Engine
Handles all CLI subcommands:
- `validate` — Design validation
- `generate` — KiCad artifact generation
- `scaffold` — Create design spec from template
- `apply-patch` — Transactional design updates
- `cost-bom` — BOM costing
- `design-wizard` — Interactive design workflow

### `design_ir.py` — Design Intermediate Representation
Dataclasses for:
- `DesignIR` — Full design document
- `DesignBlock` — Circuit block (IC + passives)
- `DesignInterface` — Signal/power connections

### `validator.py` — Validation Rules
Validation categories:
- Structural: Topology, hierarchy
- Electrical: Power, ground, connectivity
- Implementation: Symbol bindings, footprints
- Presentation: Rendering hints

### `generator.py` — KiCad Generation
Produces:
- `.kicad_sch` schematic files
- `.kicad_pcb` board templates
- SVG placement exports
- Design reports (Markdown)

## Common Tasks

### Adding a New Template (e.g., new IC template)

1. Create `src/circuit_weaver/subcircuits/my_template.py` inheriting from `SubcircuitTemplate`
2. Register in `get_default_registry()` in `subcircuits/__init__.py`
3. Add test samples in `samples/my_template/`
4. Run validation: `python -m pytest tests/test_presentation.py -v`

### Adding a New CLI Subcommand

1. Add subparser in `main()` function
2. Implement dispatch logic: `if args.command == "my-command":`
3. Add tests in `tests/test_dispatcher.py`
4. Document in `docs/cli-reference.md`

### Updating Validation Rules

1. Edit validation function in `validator.py`
2. Add `ValidationMessage` with clear error code and suggestion
3. Add regression test in `tests/test_presentation.py` or `test_import_pipeline.py`
4. Update `docs/validation-codes.md`

## Release Process

Releases are automated via GitHub Actions (triggered by git tag):

1. Tag a commit: `git tag v0.14.0`
2. Push tag: `git push origin v0.14.0`
3. GitHub Actions runs tests, builds, and publishes to PyPI
4. GitHub Release created with auto-generated notes

Version numbers follow [semver](https://semver.org/): `major.minor.patch`

## Documentation

- **User docs:** `docs/` directory (Markdown)
- **Code docstrings:** Google-style on public functions
- **Architecture:** `docs/architecture.md`
- **Changelog:** `CHANGELOG.md` (updated per sprint)

## Getting Help

- **Issues:** Open a GitHub issue for bugs or feature requests
- **Discussions:** Use GitHub Discussions for design questions
- **Documentation:** Check `docs/` and inline docstrings first
- **Community:** Reach out via issue or PR comments

## Code of Conduct

Be respectful, inclusive, and constructive in all interactions.

---

**Happy coding!** 🎉
