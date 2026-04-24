#!/usr/bin/env bash
set -euo pipefail

# Circuit Weaver Installation Script (Mac/Linux)
# Installs Python package + Claude Code + Kilo skills
#
# Usage:
#   ./install.sh                  # all platforms
#   ./install.sh claude           # Claude Code only
#   ./install.sh kilo             # Kilo CLI only
#   ./install.sh claude,kilo      # Claude Code + Kilo
#   ./install.sh python           # CLI only
#
# Project templates:
#   ./install.sh --project-platform kilo
#   ./install.sh --project-platform agents
#   ./install.sh --project-platform claude,kilo

PLATFORM="${1:-all}"
PROJECT_PLATFORM=""

if [[ "$1" == "--project-platform" ]]; then
    PROJECT_PLATFORM="$2"
    PLATFORM="python"
fi

echo ""
echo "Circuit Weaver Installation"
echo "==========================="
echo ""

# Determine which platforms to install
if [[ "$PLATFORM" == "all" ]]; then
    INSTALL_PYTHON=true
    INSTALL_CLAUDE=true
    INSTALL_KILO=true
elif [[ "$PLATFORM" == "python" ]]; then
    INSTALL_PYTHON=true
    INSTALL_CLAUDE=false
    INSTALL_KILO=false
else
    INSTALL_PYTHON=true
    INSTALL_CLAUDE=false
    INSTALL_KILO=false
    IFS=',' read -ra PFS <<< "$PLATFORM"
    for pf in "${PFS[@]}"; do
        case "$pf" in
            claude) INSTALL_CLAUDE=true ;;
            kilo)   INSTALL_KILO=true ;;
            python) INSTALL_PYTHON=true ;;
        esac
    done
fi

# Step 1: Install Python package
echo "[1/3] Installing Python package..."
python3 -m pip install -e ".[all]" --quiet
echo "[OK] circuit-weaver package installed"

# Step 2: Verify command works
echo "[2/3] Verifying installation..."
if command -v circuit-weaver &> /dev/null; then
    echo "[OK] circuit-weaver command found"
else
    echo "[WARNING] circuit-weaver not in PATH. You may need to restart your shell."
fi

# Step 3: Install platform skills
echo "[3/3] Installing platform skills..."

# --- Claude Code ---
if [[ "$INSTALL_CLAUDE" == "true" ]]; then
    SKILLS_DIR="$HOME/.claude/skills/circuit-weaver"
    SKILL_FILE="skills/circuit-weaver/SKILL.md"

    if [[ ! -f "$SKILL_FILE" ]]; then
        echo "[FAIL] SKILL.md not found at $SKILL_FILE"
        echo "Make sure you're running this from the kicad_automations repo root"
        exit 1
    fi

    mkdir -p "$SKILLS_DIR"
    cp "$SKILL_FILE" "$SKILLS_DIR/"
    echo "[OK] /circuit-weaver skill installed to Claude Code ($SKILLS_DIR)"
fi

# --- Kilo CLI ---
if [[ "$INSTALL_KILO" == "true" ]]; then
    KILO_SKILLS_DIR="$HOME/.kilo/skills/circuit-weaver"
    KILO_CONFIG_DIR="$HOME/.config/kilo"
    SKILL_FILE="skills/circuit-weaver/SKILL.md"

    if [[ ! -f "$SKILL_FILE" ]]; then
        echo "[FAIL] SKILL.md not found at $SKILL_FILE"
        exit 1
    fi

    mkdir -p "$KILO_SKILLS_DIR"
    cp "$SKILL_FILE" "$KILO_SKILLS_DIR/"

    # Install kilo.json to Kilo config directory
    if [[ -f "kilo.json" ]]; then
        mkdir -p "$KILO_CONFIG_DIR"
        cp "kilo.json" "$KILO_CONFIG_DIR/kilo.json"
        echo "[OK] kilo.json installed to $KILO_CONFIG_DIR"
    fi

    # Install .kilo/commands to Kilo commands directory
    if [[ -d ".kilo/commands" ]]; then
        KILO_COMMANDS_DIR="$KILO_CONFIG_DIR/commands"
        mkdir -p "$KILO_COMMANDS_DIR"
        cp .kilo/commands/* "$KILO_COMMANDS_DIR/"
        echo "[OK] Kilo commands installed to $KILO_COMMANDS_DIR"
    fi

    echo "[OK] /circuit-weaver skill installed to Kilo ($KILO_SKILLS_DIR)"
fi

# --- Project-level templates ---
if [[ -n "$PROJECT_PLATFORM" ]]; then
    IFS=',' read -ra PPS <<< "$PROJECT_PLATFORM"
    for pp in "${PPS[@]}"; do
        case "$pp" in
            kilo)   BASE_DIR=".kilo/skills" ;;
            agents) BASE_DIR=".agents/skills" ;;
            claude) BASE_DIR=".claude/skills" ;;
            *)      echo "[WARN] Unknown project platform: $pp"; continue ;;
        esac

        for skill_dir in project-skills/*/; do
            skill_name=$(basename "$skill_dir")
            kebab_name=$(echo "$skill_name" | tr '_' '-')
            src_file="${skill_dir}SKILL.md"
            if [[ -f "$src_file" ]]; then
                mkdir -p "$BASE_DIR/$kebab_name"
                cp "$src_file" "$BASE_DIR/$kebab_name/SKILL.md"
            fi
        done
        echo "[OK] Project templates installed to $BASE_DIR"
    done
fi

# Done
echo ""
echo "Installation Complete!"
echo "======================"
echo ""
echo "Next steps:"
echo "  1. Verify: circuit-weaver --version"
if [[ "$INSTALL_KILO" == "true" ]]; then
    echo "  2. (Kilo) Restart Kilo CLI for skills and commands to be discovered"
fi
if [[ "$INSTALL_CLAUDE" == "true" ]]; then
    echo "  2. (Claude Code) Restart Claude Code completely"
fi
echo "  3. Try: /validate, /generate, /review in any circuit-weaver project"
echo ""
echo "Optional: Set Perplexity API key for IC research"
echo "  export PERPLEXITY_API_KEY='pplx-xxx...'"
echo ""
