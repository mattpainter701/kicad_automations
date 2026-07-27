#!/usr/bin/env python3
"""Render the README capability contract from the checked-in registry.

Usage:
    python scripts/gen_capability_docs.py
    python scripts/gen_capability_docs.py --check
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SOURCE_ROOT = REPO_ROOT / "src"
README_PATH = REPO_ROOT / "README.md"
START_MARKER = "<!-- capability-registry:start -->"
END_MARKER = "<!-- capability-registry:end -->"

sys.path.insert(0, str(SOURCE_ROOT))

from circuit_weaver.capabilities import CAPABILITIES, NOT_APPLICABLE  # noqa: E402


def _escape(value: str) -> str:
    """Make a registry value safe for a Markdown table cell."""

    return value.replace("|", "\\|")


def _surfaces(record: dict[str, object]) -> str:
    surfaces = record["surfaces"]
    assert isinstance(surfaces, dict)
    labels = {"cli": "CLI", "python": "Python", "http": "HTTP", "mcp": "MCP", "skill": "Skill"}
    return "; ".join(f"{labels[name]}: `{value}`" for name, value in surfaces.items() if value) or "—"


def _verification(record: dict[str, object]) -> str:
    prerequisite = record["verification_prereq"]
    guarantee = record["output_guarantee"]
    if prerequisite == NOT_APPLICABLE:
        return "not applicable (operational)"
    return f"`{prerequisite}` → `{guarantee}`"


def render_capability_table() -> str:
    """Return the stable README section generated from ``CAPABILITIES``."""

    rows = [
        START_MARKER,
        "## Capability Contract",
        "",
        "This table is generated from the checked-in capability registry. Regenerate it with "
        "`python scripts/gen_capability_docs.py`; do not edit it by hand.",
        "",
        "Verification is conservative: a capability only claims the evidence level its public path "
        "actually verifies. **not applicable** means an operational capability makes no design-artifact "
        "verification claim; it is not a lower verification level.",
        "",
        "| CLI capability | Maturity | Public surfaces | Verification contract | Evidence | Since |",
        "|---|---|---|---|---|---|",
    ]
    for record in CAPABILITIES:
        rows.append(
            "| "
            f"`{record['surfaces']['cli']}` | {record['maturity']} | {_escape(_surfaces(record))} | "
            f"{_verification(record)} | {', '.join(f'`{kind}`' for kind in record['evidence_kinds'])} | "
            f"{record['since_version']} |"
        )
    rows.extend([END_MARKER, ""])
    return "\n".join(rows)


def update_readme(readme_path: Path = README_PATH, *, check: bool = False) -> bool:
    """Replace the marked README section and return whether it was already current."""

    text = readme_path.read_text(encoding="utf-8")
    start = text.find(START_MARKER)
    end = text.find(END_MARKER)
    if start == -1 or end == -1 or end < start:
        raise ValueError(f"{readme_path}: missing or malformed capability registry markers")
    end += len(END_MARKER)
    updated = text[:start] + render_capability_table().rstrip() + text[end:]
    current = updated == text
    if check:
        return current
    if not current:
        readme_path.write_text(updated, encoding="utf-8")
    return current


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="fail if README capability docs have drifted")
    args = parser.parse_args(argv)
    current = update_readme(check=args.check)
    if args.check and not current:
        print("README capability contract is out of date; run python scripts/gen_capability_docs.py", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
