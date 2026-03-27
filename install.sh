#!/usr/bin/env bash
# install.sh — Install kicad_automations skills into Claude Code
# Usage: ./install.sh [--skills-dir DIR] [--project-skills-dir DIR]

set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILLS_TARGET="${HOME}/.claude/skills"
PROJECT_SKILLS_TARGET=""

# Parse args
while [[ $# -gt 0 ]]; do
    case "$1" in
        --skills-dir)
            SKILLS_TARGET="$2"; shift 2 ;;
        --project-skills-dir)
            PROJECT_SKILLS_TARGET="$2"; shift 2 ;;
        -h|--help)
            echo "Usage: $0 [--skills-dir DIR] [--project-skills-dir DIR]"
            echo ""
            echo "  --skills-dir DIR           Global skills destination (default: ~/.claude/skills)"
            echo "  --project-skills-dir DIR   Project skills destination (default: skip)"
            echo ""
            echo "Project skills (kicad_gen, kicad_hierarchy, etc.) are templates."
            echo "Copy them into your project's .claude/skills/ directory manually,"
            echo "or pass --project-skills-dir .claude/skills to install them now."
            exit 0 ;;
        *)
            echo "Unknown argument: $1" >&2; exit 1 ;;
    esac
done

echo "Installing global skills to: ${SKILLS_TARGET}"

# Install each global skill
GLOBAL_SKILLS=(kicad bom digikey lcsc mouser jlcpcb pcbway ee)

for skill in "${GLOBAL_SKILLS[@]}"; do
    src="${REPO_DIR}/skills/${skill}"
    dst="${SKILLS_TARGET}/${skill}"

    if [[ ! -d "$src" ]]; then
        echo "  [SKIP] ${skill} — source directory not found"
        continue
    fi

    mkdir -p "$dst"
    cp -r "$src/." "$dst/"
    echo "  [OK]   ${skill}"
done

# Install project skills if target specified
if [[ -n "$PROJECT_SKILLS_TARGET" ]]; then
    echo ""
    echo "Installing project skills to: ${PROJECT_SKILLS_TARGET}"

    PROJECT_SKILLS=(kicad_gen kicad_hierarchy kicad_validate kicad_pinmap kicad_pcb_place sim)

    for skill in "${PROJECT_SKILLS[@]}"; do
        src="${REPO_DIR}/project-skills/${skill}"
        dst="${PROJECT_SKILLS_TARGET}/${skill}"

        if [[ ! -d "$src" ]]; then
            echo "  [SKIP] ${skill} — source directory not found"
            continue
        fi

        mkdir -p "$dst"
        cp -r "$src/." "$dst/"
        echo "  [OK]   ${skill}"
    done
fi

echo ""
echo "Done. Add skills to your CLAUDE.md:"
echo ""
echo "  ## Skills"
for skill in "${GLOBAL_SKILLS[@]}"; do
    echo "  - \`${skill}\`: @~/.claude/skills/${skill}/SKILL.md"
done
echo ""
echo "Project skill templates are in: ${REPO_DIR}/project-skills/"
echo "Copy them to your project's .claude/skills/ and customize as needed."
