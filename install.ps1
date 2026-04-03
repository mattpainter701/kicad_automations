param(
    [string[]]$Platform,
    [string]$SkillsDir,
    [string[]]$ProjectPlatform,
    [string]$ProjectSkillsDir,
    [switch]$Help
)

$ErrorActionPreference = "Stop"

function Show-Help {
    @"
Usage: ./install.ps1 [-Platform LIST] [-SkillsDir DIR] [-ProjectPlatform LIST] [-ProjectSkillsDir DIR]

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
  - -SkillsDir adds one explicit global destination in addition to any -Platform targets.
  - -ProjectSkillsDir adds one explicit project destination in addition to any -ProjectPlatform targets.
  - There is no implicit default platform. Pass -Platform, -SkillsDir, -ProjectPlatform, or -ProjectSkillsDir.
  - Codex does not have a standard project-local skills directory; install globally or point -ProjectSkillsDir at a custom path.
  - OpenCode/Kilo/open-agent project installs convert underscore template names like kicad_gen to kebab-case IDs like kicad-gen.

Examples:
  ./install.ps1 -Platform all
  ./install.ps1 -Platform codex,opencode,kilo
  ./install.ps1 -ProjectPlatform agents
  ./install.ps1 -ProjectPlatform claude,opencode
"@
}

if ($Help) {
    Show-Help
    exit 0
}

$repoDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$globalSkills = @("kicad", "bom", "digikey", "lcsc", "mouser", "jlcpcb", "pcbway", "ee", "vivado")
$projectSkills = @("autoroute", "kicad_gen", "kicad_hierarchy", "kicad_validate", "kicad_pinmap", "kicad_pcb_place", "sim")
$globalTargets = New-Object System.Collections.Generic.List[string]
$projectTargets = New-Object System.Collections.Generic.List[string]

function Add-UniqueTarget {
    param(
        [System.Collections.Generic.List[string]]$List,
        [string]$Value
    )

    if (-not [string]::IsNullOrWhiteSpace($Value) -and -not $List.Contains($Value)) {
        $List.Add($Value) | Out-Null
    }
}

function Get-GlobalPlatformPath {
    param([string]$Name)

    switch ($Name.ToLowerInvariant()) {
        "claude" { return (Join-Path $HOME ".claude/skills") }
        "codex" { return (Join-Path $HOME ".codex/skills") }
        "opencode" { return (Join-Path $HOME ".config/opencode/skills") }
        "kilo" { return (Join-Path $HOME ".kilo/skills") }
        default { throw "Unsupported global platform: $Name" }
    }
}

function Get-ProjectPlatformPath {
    param([string]$Name)

    switch ($Name.ToLowerInvariant()) {
        "claude" { return ".claude/skills" }
        "opencode" { return ".opencode/skills" }
        "kilo" { return ".kilo/skills" }
        "agents" { return ".agents/skills" }
        "codex" { throw "Codex does not have a standard project-local skills directory. Use -Platform codex for ~/.codex/skills or point -ProjectSkillsDir at a custom path." }
        default { throw "Unsupported project platform: $Name" }
    }
}

function Expand-PlatformValues {
    param(
        [string[]]$Values,
        [ValidateSet("global", "project")] [string]$Kind
    )

    foreach ($value in $Values) {
        if ([string]::IsNullOrWhiteSpace($value)) {
            continue
        }

        foreach ($item in ($value -split ",")) {
            $normalized = $item.Trim().ToLowerInvariant()
            if (-not $normalized) {
                continue
            }

            if ($normalized -eq "all") {
                $expanded = if ($Kind -eq "global") {
                    @("claude", "codex", "opencode", "kilo")
                } else {
                    @("claude", "opencode", "kilo", "agents")
                }
            } else {
                $expanded = @($normalized)
            }

            foreach ($entry in $expanded) {
                if ($Kind -eq "global") {
                    Add-UniqueTarget -List $globalTargets -Value (Get-GlobalPlatformPath $entry)
                } else {
                    Add-UniqueTarget -List $projectTargets -Value (Get-ProjectPlatformPath $entry)
                }
            }
        }
    }
}

function Test-OpenAgentSkillDir {
    param([string]$Path)

    return $Path -match '(^|[\\/])\.(opencode|kilo|agents)[\\/]+skills([\\/]|$)'
}

function Update-SkillFrontmatterName {
    param(
        [string]$SkillFile,
        [string]$NewName
    )

    if (-not (Test-Path -LiteralPath $SkillFile)) {
        return
    }

    $text = Get-Content -LiteralPath $SkillFile -Raw
    $pattern = '^(---\r?\n)(.*?)(\r?\n---\r?\n)'
    $match = [regex]::Match($text, $pattern, [System.Text.RegularExpressions.RegexOptions]::Singleline)
    if (-not $match.Success) {
        return
    }

    $frontmatter = $match.Groups[2].Value
    if ($frontmatter -match '(?m)^name:\s*.*$') {
        $frontmatter = [regex]::Replace($frontmatter, '(?m)^name:\s*.*$', "name: $NewName", 1)
    } else {
        $frontmatter = "name: $NewName`n$frontmatter"
    }

    $updated = "---`n$frontmatter`n---`n" + $text.Substring($match.Length)
    Set-Content -LiteralPath $SkillFile -Value $updated -NoNewline
}

function Install-SkillTree {
    param(
        [string]$SourceRoot,
        [string]$TargetRoot,
        [string]$SourceName,
        [ValidateSet("global", "project")] [string]$SkillType
    )

    $targetName = $SourceName
    if ($SkillType -eq "project" -and (Test-OpenAgentSkillDir $TargetRoot)) {
        $targetName = $SourceName -replace "_", "-"
    }

    $sourceDir = Join-Path $repoDir $SourceRoot
    $sourceDir = Join-Path $sourceDir $SourceName
    $targetDir = Join-Path $TargetRoot $targetName

    if (-not (Test-Path -LiteralPath $sourceDir -PathType Container)) {
        Write-Host "  [SKIP] $SourceName - source directory not found"
        return
    }

    New-Item -ItemType Directory -Path $targetDir -Force | Out-Null
    Get-ChildItem -LiteralPath $sourceDir -Force | ForEach-Object {
        Copy-Item -LiteralPath $_.FullName -Destination $targetDir -Recurse -Force
    }

    if ($targetName -ne $SourceName) {
        Update-SkillFrontmatterName -SkillFile (Join-Path $targetDir "SKILL.md") -NewName $targetName
        Write-Host "  [OK]   $SourceName -> $targetName"
    } else {
        Write-Host "  [OK]   $SourceName"
    }
}

Expand-PlatformValues -Values $Platform -Kind global
Expand-PlatformValues -Values $ProjectPlatform -Kind project

if ($SkillsDir) {
    Add-UniqueTarget -List $globalTargets -Value $SkillsDir
}

if ($ProjectSkillsDir) {
    Add-UniqueTarget -List $projectTargets -Value $ProjectSkillsDir
}

if ($globalTargets.Count -eq 0 -and $projectTargets.Count -eq 0) {
    Write-Error "No install target specified. Pass -Platform, -SkillsDir, -ProjectPlatform, or -ProjectSkillsDir."
}

foreach ($target in $globalTargets) {
    Write-Host "Installing global skills to: $target"
    foreach ($skill in $globalSkills) {
        Install-SkillTree -SourceRoot "skills" -TargetRoot $target -SourceName $skill -SkillType global
    }
    Write-Host ""
}

foreach ($target in $projectTargets) {
    Write-Host "Installing project skills to: $target"
    foreach ($skill in $projectSkills) {
        Install-SkillTree -SourceRoot "project-skills" -TargetRoot $target -SourceName $skill -SkillType project
    }
    Write-Host ""
}

Write-Host "Done."
Write-Host "Canonical skill sources live in: $repoDir/skills/"
Write-Host "Project skill templates live in: $repoDir/project-skills/"
Write-Host "Codex/OpenCode/Kilo repo-level instructions live in AGENTS.md at the repo root."
