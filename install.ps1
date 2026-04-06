#!/usr/bin/env pwsh
<#
.SYNOPSIS
    Install Circuit Weaver globally on Windows (Python + Claude Code skills)

.DESCRIPTION
    Installs the circuit-weaver Python package and registers the /circuit-weaver skill
    with Claude Code for use in any project.

.PARAMETER Platform
    Target platform(s): 'claude' (Claude Code), 'python' (CLI only), 'all' (default)

.EXAMPLE
    ./install.ps1
    ./install.ps1 -Platform claude
    ./install.ps1 -Platform all
#>

param(
    [ValidateSet('claude', 'python', 'all')]
    [string]$Platform = 'all'
)

$ErrorActionPreference = 'Stop'

Write-Host "Circuit Weaver Installation" -ForegroundColor Cyan
Write-Host "===========================" -ForegroundColor Cyan
Write-Host ""

# Step 1: Install Python package
Write-Host "[1/3] Installing Python package..." -ForegroundColor Yellow

try {
    py -m pip install -e ".[all]" --quiet
    Write-Host "[OK] circuit-weaver package installed" -ForegroundColor Green
} catch {
    Write-Host "[FAIL] Could not install package" -ForegroundColor Red
    Write-Host "Error: $_" -ForegroundColor Red
    exit 1
}

# Step 2: Add Python Scripts to PATH (if needed)
Write-Host "[2/3] Checking PATH..." -ForegroundColor Yellow

$PythonScripts = "C:\Python313\Scripts"
$CurrentPath = [Environment]::GetEnvironmentVariable("PATH", "User")

if ($null -eq $CurrentPath -or -not $CurrentPath.Contains($PythonScripts)) {
    Write-Host "Adding Python Scripts directory to PATH..." -ForegroundColor Cyan
    $NewPath = if ($CurrentPath) { "$CurrentPath;$PythonScripts" } else { $PythonScripts }
    [Environment]::SetEnvironmentVariable("PATH", $NewPath, "User")
    Write-Host "[OK] PATH updated. You may need to restart your terminal." -ForegroundColor Green
} else {
    Write-Host "[OK] Python Scripts already in PATH" -ForegroundColor Green
}

# Step 3: Install Claude Code skill (if requested)
if ($Platform -eq 'claude' -or $Platform -eq 'all') {
    Write-Host "[3/3] Installing Claude Code skill..." -ForegroundColor Yellow

    $SkillsDir = "$env:USERPROFILE\.claude\skills\circuit-weaver"
    $SkillFile = "skills/circuit-weaver/SKILL.md"

    if (-not (Test-Path $SkillFile)) {
        Write-Host "[FAIL] SKILL.md not found at $SkillFile" -ForegroundColor Red
        Write-Host "Make sure you're running this from the kicad_automations repo root" -ForegroundColor Red
        exit 1
    }

    mkdir -Force $SkillsDir | Out-Null
    Copy-Item -Path $SkillFile -Destination $SkillsDir -Force
    Write-Host "[OK] /circuit-weaver skill installed to $SkillsDir" -ForegroundColor Green
    Write-Host "" -ForegroundColor Yellow
    Write-Host "IMPORTANT: Restart Claude Code completely (close all windows) for the skill to be discovered." -ForegroundColor Yellow
} else {
    Write-Host "[3/3] Skipping Claude Code skill" -ForegroundColor Yellow
}

# Done
Write-Host ""
Write-Host "Installation Complete!" -ForegroundColor Green
Write-Host "======================" -ForegroundColor Green
Write-Host ""
Write-Host "Next steps:" -ForegroundColor Cyan
Write-Host "  1. Verify: circuit-weaver --version" -ForegroundColor White
Write-Host "  2. (Claude Code only) Restart Claude Code completely" -ForegroundColor White
Write-Host "  3. Try: /circuit-weaver in any Claude Code project" -ForegroundColor White
Write-Host ""
Write-Host "Optional: Set Perplexity API key for IC research" -ForegroundColor Cyan
Write-Host "  `$env:PERPLEXITY_API_KEY = 'pplx-xxx...'" -ForegroundColor White
Write-Host ""
