[CmdletBinding()]
param(
    [string[]]$Platform = @("all"),
    [string[]]$Skill = @(),
    [switch]$Force,
    [switch]$Backup,
    [switch]$DryRun,
    [switch]$SkillsOnly,
    [switch]$PythonOnly
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

if ($SkillsOnly -and $PythonOnly) {
    throw "-SkillsOnly and -PythonOnly are mutually exclusive."
}
if ($Backup -and -not $Force) {
    throw "-Backup requires -Force."
}
if ($PythonOnly -and $PSBoundParameters.ContainsKey("Platform")) {
    throw "-PythonOnly cannot be combined with -Platform."
}

$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Push-Location $scriptRoot
try {
    $python = Get-Command py -ErrorAction SilentlyContinue
    if (-not $python) {
        $python = Get-Command python -ErrorAction SilentlyContinue
    }
    if (-not $python) {
        throw "Python 3 was not found. Install Python and ensure 'py' or 'python' is on PATH."
    }

    $requestedPlatforms = @()
    if (-not $PythonOnly) {
        foreach ($value in $Platform) {
            $requestedPlatforms += $value.Split(",", [System.StringSplitOptions]::RemoveEmptyEntries)
        }
    }

    $agentPlatforms = @()
    foreach ($value in $requestedPlatforms) {
        switch ($value.ToLowerInvariant()) {
            "all" {
                $agentPlatforms = @("all")
                break
            }
            "claude" { $agentPlatforms += "claude" }
            "codex" { $agentPlatforms += "codex" }
            "opencode" { $agentPlatforms += "opencode" }
            "kilo" { $agentPlatforms += "kilo" }
            "python" { $PythonOnly = $true }
            default { throw "Unknown platform '$value'. Use all, claude, codex, opencode, kilo, or python." }
        }
        if ($agentPlatforms -contains "all") { break }
    }

    if (-not $SkillsOnly) {
        Write-Host "[1/2] Installing Circuit Weaver from this checkout..."
        & $python.Source -m pip install -e ".[all]"
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    }

    if ($PythonOnly -and $agentPlatforms.Count -eq 0) {
        Write-Host "[OK] Python package installed"
        exit 0
    }
    if ($agentPlatforms.Count -eq 0) {
        $agentPlatforms = @("all")
    }

    $installArgs = @("-m", "circuit_weaver", "install-skills", "--platform") + $agentPlatforms
    if ($Skill.Count -gt 0) { $installArgs += @("--skills") + $Skill }
    if ($Force) { $installArgs += "--force" }
    if ($Backup) { $installArgs += "--backup" }
    if ($DryRun) { $installArgs += "--dry-run" }

    Write-Host "[2/2] Installing agent skills..."
    & $python.Source @installArgs
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    Write-Host "[OK] Circuit Weaver installation complete"
}
finally {
    Pop-Location
}
