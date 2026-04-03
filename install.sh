#!/usr/bin/env bash
# install.sh — Install Circuit Weaver skills for supported agent platforms.
# Usage:
#   ./install.sh [--platform LIST] [--skills-dir DIR]
#                [--project-platform LIST] [--project-skills-dir DIR]

set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GLOBAL_SKILLS=(kicad bom digikey lcsc mouser jlcpcb pcbway ee vivado)
PROJECT_SKILLS=(autoroute kicad_gen kicad_hierarchy kicad_validate kicad_pinmap kicad_pcb_place sim)
GLOBAL_TARGETS=()
PROJECT_TARGETS=()

append_unique() {
    local value="$1"
    local existing
    for existing in "${@:2}"; do
        if [[ "$existing" == "$value" ]]; then
            return 0
        fi
    done
    return 1
}

lower_trim() {
    printf '%s' "$1" \
        | tr '[:upper:]' '[:lower:]' \
        | sed 's/^[[:space:]]*//; s/[[:space:]]*$//'
}

global_platform_dir() {
    case "$1" in
        claude) printf '%s/.claude/skills' "${HOME}" ;;
        codex) printf '%s/.codex/skills' "${HOME}" ;;
        opencode) printf '%s/.config/opencode/skills' "${HOME}" ;;
        kilo) printf '%s/.kilo/skills' "${HOME}" ;;
        *)
            echo "Unsupported global platform: $1" >&2
            exit 1
            ;;
    esac
}

project_platform_dir() {
    case "$1" in
        claude) printf '.claude/skills' ;;
        opencode) printf '.opencode/skills' ;;
        kilo) printf '.kilo/skills' ;;
        agents) printf '.agents/skills' ;;
        codex)
            echo "Codex does not have a standard project-local skills directory. Use --platform codex for ~/.codex/skills or point --project-skills-dir at a custom path." >&2
            exit 1
            ;;
        *)
            echo "Unsupported project platform: $1" >&2
            exit 1
            ;;
    esac
}

expand_platform_arg() {
    local kind="$1"
    local raw="$2"
    local IFS=','
    local item normalized target
    local -a parts
    read -r -a parts <<< "$raw"
    for item in "${parts[@]}"; do
        normalized="$(lower_trim "$item")"
        [[ -z "$normalized" ]] && continue
        if [[ "$normalized" == "all" ]]; then
            if [[ "$kind" == "global" ]]; then
                for normalized in claude codex opencode kilo; do
                    target="$(global_platform_dir "$normalized")"
                    if ! append_unique "$target" "${GLOBAL_TARGETS[@]}"; then
                        GLOBAL_TARGETS+=("$target")
                    fi
                done
            else
                for normalized in claude opencode kilo agents; do
                    target="$(project_platform_dir "$normalized")"
                    if ! append_unique "$target" "${PROJECT_TARGETS[@]}"; then
                        PROJECT_TARGETS+=("$target")
                    fi
                done
            fi
            continue
        fi

        if [[ "$kind" == "global" ]]; then
            target="$(global_platform_dir "$normalized")"
            if ! append_unique "$target" "${GLOBAL_TARGETS[@]}"; then
                GLOBAL_TARGETS+=("$target")
            fi
        else
            target="$(project_platform_dir "$normalized")"
            if ! append_unique "$target" "${PROJECT_TARGETS[@]}"; then
                PROJECT_TARGETS+=("$target")
            fi
        fi
    done
}

is_open_agent_skill_dir() {
    case "$1" in
        *".opencode/skills"*|*".kilo/skills"*|*".agents/skills"*)
            return 0
            ;;
        *)
            return 1
            ;;
    esac
}

rewrite_skill_name() {
    local skill_file="$1"
    local new_name="$2"
    local -a python_cmd

    [[ -f "$skill_file" ]] || return 0

    if command -v python3 >/dev/null 2>&1; then
        python_cmd=(python3)
    elif command -v python >/dev/null 2>&1; then
        python_cmd=(python)
    elif command -v py >/dev/null 2>&1; then
        python_cmd=(py -3)
    else
        echo "A Python interpreter is required to rewrite SKILL.md frontmatter during open-agent project installs." >&2
        exit 1
    fi

    "${python_cmd[@]}" - "$skill_file" "$new_name" <<'PY'
import re
import sys
from pathlib import Path

path = Path(sys.argv[1])
new_name = sys.argv[2]
text = path.read_text(encoding="utf-8")
match = re.match(r"\A---\r?\n(.*?)\r?\n---\r?\n", text, re.DOTALL)
if not match:
    raise SystemExit(0)

frontmatter = match.group(1)
if re.search(r"(?m)^name:\s*.*$", frontmatter):
    frontmatter = re.sub(r"(?m)^name:\s*.*$", f"name: {new_name}", frontmatter, count=1)
else:
    frontmatter = f"name: {new_name}\n{frontmatter}"

path.write_text(f"---\n{frontmatter}\n---\n{text[match.end():]}", encoding="utf-8", newline="\n")
PY
}

install_skill_tree() {
    local source_root="$1"
    local target_root="$2"
    local source_name="$3"
    local skill_type="$4"
    local target_name="$source_name"

    if [[ "$skill_type" == "project" ]] && is_open_agent_skill_dir "$target_root"; then
        target_name="${source_name//_/-}"
    fi

    local source_dir="${REPO_DIR}/${source_root}/${source_name}"
    local target_dir="${target_root}/${target_name}"

    if [[ ! -d "$source_dir" ]]; then
        echo "  [SKIP] ${source_name} — source directory not found"
        return 0
    fi

    mkdir -p "$target_dir"
    cp -r "$source_dir/." "$target_dir/"

    if [[ "$target_name" != "$source_name" ]]; then
        rewrite_skill_name "${target_dir}/SKILL.md" "$target_name"
        echo "  [OK]   ${source_name} -> ${target_name}"
    else
        echo "  [OK]   ${source_name}"
    fi
}

show_help() {
    cat <<'EOF'
Usage: ./install.sh [--platform LIST] [--skills-dir DIR] [--project-platform LIST] [--project-skills-dir DIR]

Global platform targets:
  claude    -> ~/.claude/skills
  codex     -> ~/.codex/skills
  opencode  -> ~/.config/opencode/skills
  kilo      -> ~/.kilo/skills
  all       -> claude,codex,opencode,kilo

Project platform targets:
  claude    -> .claude/skills
  opencode  -> .opencode/skills
  kilo      -> .kilo/skills
  agents    -> .agents/skills
  all       -> claude,opencode,kilo,agents

Notes:
  - --skills-dir adds one explicit global destination in addition to any --platform targets.
  - --project-skills-dir adds one explicit project destination in addition to any --project-platform targets.
  - There is no implicit default platform. Pass --platform, --skills-dir, --project-platform, or --project-skills-dir.
  - Codex does not have a standard project-local skills directory; install globally or point --project-skills-dir at a custom path.
  - OpenCode/Kilo/open-agent project installs convert underscore template names like kicad_gen to kebab-case IDs like kicad-gen.

Examples:
  ./install.sh --platform all
  ./install.sh --platform codex,opencode,kilo
  ./install.sh --project-platform agents
  ./install.sh --project-platform claude --project-platform opencode
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --platform)
            expand_platform_arg "global" "$2"
            shift 2
            ;;
        --skills-dir)
            if ! append_unique "$2" "${GLOBAL_TARGETS[@]}"; then
                GLOBAL_TARGETS+=("$2")
            fi
            shift 2
            ;;
        --project-platform)
            expand_platform_arg "project" "$2"
            shift 2
            ;;
        --project-skills-dir)
            if ! append_unique "$2" "${PROJECT_TARGETS[@]}"; then
                PROJECT_TARGETS+=("$2")
            fi
            shift 2
            ;;
        -h|--help)
            show_help
            exit 0
            ;;
        *)
            echo "Unknown argument: $1" >&2
            exit 1
            ;;
    esac
done

if [[ "${#GLOBAL_TARGETS[@]}" -eq 0 && "${#PROJECT_TARGETS[@]}" -eq 0 ]]; then
    echo "No install target specified. Pass --platform, --skills-dir, --project-platform, or --project-skills-dir." >&2
    echo "" >&2
    show_help >&2
    exit 1
fi

for target in "${GLOBAL_TARGETS[@]}"; do
    echo "Installing global skills to: ${target}"
    for skill in "${GLOBAL_SKILLS[@]}"; do
        install_skill_tree "skills" "$target" "$skill" "global"
    done
    echo ""
done

for target in "${PROJECT_TARGETS[@]}"; do
    echo "Installing project skills to: ${target}"
    for skill in "${PROJECT_SKILLS[@]}"; do
        install_skill_tree "project-skills" "$target" "$skill" "project"
    done
    echo ""
done

echo "Done."
echo "Canonical skill sources live in: ${REPO_DIR}/skills/"
echo "Project skill templates live in: ${REPO_DIR}/project-skills/"
echo "Codex/OpenCode/Kilo repo-level instructions live in AGENTS.md at the repo root."
