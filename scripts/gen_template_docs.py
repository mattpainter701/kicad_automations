#!/usr/bin/env python3
"""Generate docs/templates.md from the subcircuit template registry."""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure the package is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from circuit_weaver.subcircuits.base import get_default_registry


def main() -> None:
    registry = get_default_registry()
    lines = [
        "# Template Reference",
        "",
        "Auto-generated from `param_schema` of all registered subcircuit templates.",
        "",
        f"**{len(list(registry.available_types()))} templates available.**",
        "",
        "---",
        "",
    ]

    for ttype in sorted(registry.available_types()):
        tmpl = registry.get(ttype)
        lines.append(f"## `{ttype}`")
        lines.append("")
        lines.append(tmpl.description)
        lines.append("")

        schema = tmpl.param_schema
        if schema:
            lines.append("### Parameters")
            lines.append("")
            lines.append("| Name | Type | Required | Default | Options |")
            lines.append("|------|------|----------|---------|---------|")
            for spec in schema:
                name = spec.get("name", "")
                ptype = spec.get("type", "")
                required = "Yes" if spec.get("required") else ""
                default = str(spec["default"]) if "default" in spec else ""
                options = ", ".join(str(o) for o in spec["options"]) if "options" in spec else ""
                lines.append(f"| `{name}` | {ptype} | {required} | {default} | {options} |")
            lines.append("")

        # Example YAML snippet
        lines.append("### Example")
        lines.append("")
        lines.append("```yaml")
        lines.append("power:")
        lines.append(f"  - type: {ttype}")
        lines.append("    ref: U1")
        for spec in schema:
            name = spec.get("name", "")
            if name in ("ref",):
                continue
            if spec.get("required"):
                if spec.get("type") == "number":
                    lines.append(f"    {name}: 3.3")
                elif "options" in spec:
                    lines.append(f"    {name}: {spec['options'][0]}")
                else:
                    lines.append(f"    {name}: <value>")
        lines.append("```")
        lines.append("")
        lines.append("---")
        lines.append("")

    output_path = Path(__file__).resolve().parent.parent / "docs" / "templates.md"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"Generated {output_path} ({len(list(registry.available_types()))} templates)")


if __name__ == "__main__":
    main()
