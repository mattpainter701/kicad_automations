#!/usr/bin/env bash
set -euo pipefail

# Thin repository installer for macOS, Linux, and WSL.  Platform paths and
# collision handling live in circuit_weaver.skill_installer.

usage() {
    cat <<'EOF'
Usage: ./install.sh [options] [platforms]

Platforms may be comma-separated: all, claude, codex, opencode, kilo, python.
No platform argument means all supported agent platforms.

Options:
  --platform VALUE   Select one or more comma-separated platforms.
  --skill NAME       Install one skill; repeat for multiple skills.
  --force            Replace conflicting managed files.
  --backup           With --force, back up every replaced file.
  --dry-run          Preview skill changes.
  --skills-only      Do not install/update the Python package.
  --python-only      Install the Python package but no agent skills.
  -h, --help         Show this help.

Environment:
  CLAUDE_CONFIG_DIR and OPENCODE_CONFIG_DIR override those platforms' config
  roots. Codex uses the current Agent Skills location: ~/.agents/skills.
EOF
}

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

platform_spec="all"
platform_was_set=false
skills=()
force=false
backup=false
dry_run=false
skills_only=false
python_only=false
python_only_option=false

while (($#)); do
    case "$1" in
        --platform)
            (($# >= 2)) || { echo "[FAIL] --platform requires a value" >&2; exit 2; }
            platform_spec="$2"
            platform_was_set=true
            shift 2
            ;;
        --skill)
            (($# >= 2)) || { echo "[FAIL] --skill requires a value" >&2; exit 2; }
            skills+=("$2")
            shift 2
            ;;
        --force) force=true; shift ;;
        --backup) backup=true; shift ;;
        --dry-run) dry_run=true; shift ;;
        --skills-only) skills_only=true; shift ;;
        --python-only) python_only=true; python_only_option=true; shift ;;
        -h|--help) usage; exit 0 ;;
        --*) echo "[FAIL] Unknown option: $1" >&2; usage >&2; exit 2 ;;
        *)
            if [[ "$platform_was_set" == true ]]; then
                echo "[FAIL] Platforms were supplied both positionally and with --platform" >&2
                exit 2
            fi
            platform_spec="$1"
            platform_was_set=true
            shift
            ;;
    esac
done

if [[ "$skills_only" == true && "$python_only" == true ]]; then
    echo "[FAIL] --skills-only and --python-only are mutually exclusive" >&2
    exit 2
fi
if [[ "$python_only_option" == true && "$platform_was_set" == true ]]; then
    echo "[FAIL] --python-only cannot be combined with a platform selection" >&2
    exit 2
fi
if [[ "$backup" == true && "$force" != true ]]; then
    echo "[FAIL] --backup requires --force" >&2
    exit 2
fi

if command -v python3 >/dev/null 2>&1; then
    PYTHON_BIN="$(command -v python3)"
elif command -v python >/dev/null 2>&1; then
    PYTHON_BIN="$(command -v python)"
else
    echo "[FAIL] Python 3 was not found on PATH" >&2
    exit 1
fi

requested_platforms=()
if [[ "$python_only_option" != true ]]; then
    IFS=',' read -r -a requested_platforms <<< "$platform_spec"
fi
platforms=()
for platform in "${requested_platforms[@]}"; do
    case "$platform" in
        all)
            platforms=(all)
            break
            ;;
        claude|codex|opencode|kilo) platforms+=("$platform") ;;
        python) python_only=true ;;
        "") ;;
        *) echo "[FAIL] Unknown platform: $platform" >&2; exit 2 ;;
    esac
done

if [[ "$skills_only" != true ]]; then
    echo "[1/2] Installing Circuit Weaver from this checkout..."
    "$PYTHON_BIN" -m pip install -e ".[all]"
fi

if [[ "$python_only" == true && ${#platforms[@]} -eq 0 ]]; then
    echo "[OK] Python package installed"
    exit 0
fi
if [[ ${#platforms[@]} -eq 0 ]]; then
    platforms=(all)
fi

command_args=("$PYTHON_BIN" -m circuit_weaver install-skills --platform "${platforms[@]}")
if ((${#skills[@]})); then
    command_args+=(--skills "${skills[@]}")
fi
[[ "$force" == true ]] && command_args+=(--force)
[[ "$backup" == true ]] && command_args+=(--backup)
[[ "$dry_run" == true ]] && command_args+=(--dry-run)

echo "[2/2] Installing agent skills..."
"${command_args[@]}"
echo "[OK] Circuit Weaver installation complete"
