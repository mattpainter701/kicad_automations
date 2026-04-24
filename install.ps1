#!/usr/bin/env pwsh
<#
.SYNOPSIS
    Install Circuit Weaver globally on Windows (Python + Claude Code + Kilo skills)

.DESCRIPTION
    Installs the circuit-weaver Python package and registers skills with
    Claude Code and/or Kilo CLI for use in any project.

.PARAMETER Platform
    Target platform(s): 'claude' (Claude Code), 'kilo' (Kilo CLI), 'python' (CLI only),
    or 'all' (default). Comma-separated lists supported (e.g. 'claude,kilo').

.PARAMETER ProjectPlatform
    Install project-level templates into downstream-agent skill directories.
    Values: 'agents' (shared .agents/skills), 'kilo' (.kilo/skills),
    'claude' (.claude/skills), or comma-separated combinations.

.EXAMPLE
    ./install.ps1
    ./install.ps1 -Platform claude
    ./install.ps1 -Platform kilo
    ./install.ps1 -Platform claude,kilo
    ./install.ps1 -Platform all
    ./install.ps1 -ProjectPlatform kilo
#>

param(
    [string]$Platform = 'all',
    [string]$ProjectPlatform = ''
)

$ErrorActionPreference = 'Stop'

$Platforms = if ($Platform -eq 'all') { @('python', 'claude', 'kilo') } else { $Platform -split ',' }

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

# Step 3: Install platform skills
Write-Host "[3/3] Installing platform skills..." -ForegroundColor Yellow

# --- Claude Code ---
if ($Platforms -contains 'claude') {
    $SkillsDir = "$env:USERPROFILE\.claude\skills\circuit-weaver"
    $SkillFile = "skills/circuit-weaver/SKILL.md"

    if (-not (Test-Path $SkillFile)) {
        Write-Host "[FAIL] SKILL.md not found at $SkillFile" -ForegroundColor Red
        Write-Host "Make sure you're running this from the kicad_automations repo root" -ForegroundColor Red
        exit 1
    }

    mkdir -Force $SkillsDir | Out-Null
    Copy-Item -Path $SkillFile -Destination $SkillsDir -Force
    Write-Host "[OK] /circuit-weaver skill installed to Claude Code ($SkillsDir)" -ForegroundColor Green
}

# --- Kilo CLI ---
if ($Platforms -contains 'kilo') {
    $KiloSkillsDir = "$env:USERPROFILE\.kilo\skills\circuit-weaver"
    $SkillFile = "skills/circuit-weaver/SKILL.md"

    if (-not (Test-Path $SkillFile)) {
        Write-Host "[FAIL] SKILL.md not found at $SkillFile" -ForegroundColor Red
        exit 1
    }

    mkdir -Force $KiloSkillsDir | Out-Null
    Copy-Item -Path $SkillFile -Destination $KiloSkillsDir -Force

    # Install kilo.json to Kilo config directory
    $KiloConfigDir = "$env:USERPROFILE\.config\kilo"
    if (Test-Path "kilo.json") {
        mkdir -Force $KiloConfigDir | Out-Null
        Copy-Item -Path "kilo.json" -Destination "$KiloConfigDir\kilo.json" -Force
        Write-Host "[OK] kilo.json installed to $KiloConfigDir" -ForegroundColor Green
    }

    # Install .kilo/commands to Kilo commands directory
    if (Test-Path ".kilo\commands") {
        $KiloCommandsDir = "$KiloConfigDir\commands"
        mkdir -Force $KiloCommandsDir | Out-Null
        Copy-Item -Path ".kilo\commands\*" -Destination $KiloCommandsDir -Force
        Write-Host "[OK] Kilo commands installed to $KiloCommandsDir" -ForegroundColor Green
    }

    Write-Host "[OK] /circuit-weaver skill installed to Kilo ($KiloSkillsDir)" -ForegroundColor Green
}

# --- Project-level templates ---
if ($ProjectPlatform) {
    $ProjectPlatforms = $ProjectPlatform -split ','
    $ProjectSkills = Get-ChildItem -Path "project-skills" -Directory

    foreach ($pps in $ProjectPlatforms) {
        $baseDir = switch ($pps) {
            'kilo'   { ".kilo\skills" }
            'agents' { ".agents\skills" }
            'claude' { ".claude\skills" }
            default  { ".agents\skills" }
        }

        foreach ($skill in $ProjectSkills) {
            $srcSkillFile = Join-Path $skill.FullName "SKILL.md"
            $kebabName = $skill.Name -replace '_', '-'
            $destDir = Join-Path $baseDir $kebabName
            mkdir -Force $destDir | Out-Null
            Copy-Item -Path $srcSkillFile -Destination (Join-Path $destDir "SKILL.md") -Force
        }
        Write-Host "[OK] Project templates installed to $baseDir" -ForegroundColor Green
    }
}

# Done
Write-Host ""
Write-Host "Installation Complete!" -ForegroundColor Green
Write-Host "======================" -ForegroundColor Green
Write-Host ""
Write-Host "Next steps:" -ForegroundColor Cyan
Write-Host "  1. Verify: circuit-weaver --version" -ForegroundColor White
if ($Platforms -contains 'kilo') {
    Write-Host "  2. (Kilo) Restart Kilo CLI for skills and commands to be discovered" -ForegroundColor White
}
if ($Platforms -contains 'claude') {
    Write-Host "  2. (Claude Code) Restart Claude Code completely" -ForegroundColor White
}
Write-Host "  3. Try: /validate, /generate, /review in any circuit-weaver project" -ForegroundColor White
Write-Host ""
Write-Host "Optional: Set Perplexity API key for IC research" -ForegroundColor Cyan
Write-Host "  `$env:PERPLEXITY_API_KEY = 'pplx-xxx...'" -ForegroundColor White
Write-Host ""
