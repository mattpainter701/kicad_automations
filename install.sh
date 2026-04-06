#!/usr/bin/env bash
set -euo pipefail

# Circuit Weaver Installation Script (Mac/Linux)
# Installs Python package + Claude Code skills

PLATFORM="${1:-all}"  # claude, python, or all

echo ""
echo "Circuit Weaver Installation"
echo "==========================="
echo ""

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

# Step 3: Install Claude Code skill (if requested)
if [[ "$PLATFORM" == "claude" ]] || [[ "$PLATFORM" == "all" ]]; then
    echo "[3/3] Installing Claude Code skill..."
    
    SKILLS_DIR="$HOME/.claude/skills/circuit-weaver"
    SKILL_FILE="skills/circuit-weaver/SKILL.md"
    
    if [[ ! -f "$SKILL_FILE" ]]; then
        echo "[FAIL] SKILL.md not found at $SKILL_FILE"
        echo "Make sure you're running this from the kicad_automations repo root"
        exit 1
    fi
    
    mkdir -p "$SKILLS_DIR"
    cp "$SKILL_FILE" "$SKILLS_DIR/"
    echo "[OK] /circuit-weaver skill installed to $SKILLS_DIR"
    echo ""
    echo "IMPORTANT: Restart Claude Code completely for the skill to be discovered."
else
    echo "[3/3] Skipping Claude Code skill"
fi

# Done
echo ""
echo "Installation Complete!"
echo "======================"
echo ""
echo "Next steps:"
echo "  1. Verify: circuit-weaver --version"
echo "  2. (Claude Code only) Restart Claude Code completely"
echo "  3. Try: /circuit-weaver in any Claude Code project"
echo ""
echo "Optional: Set Perplexity API key for IC research"
echo "  export PERPLEXITY_API_KEY='pplx-xxx...'"
echo ""
