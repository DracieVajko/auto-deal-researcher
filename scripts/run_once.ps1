<# 
.SYNOPSIS
    Run Auto Deal Searcher once with specified parameters.
.DESCRIPTION
    Wrapper script for manual or scheduled runs.
.PARAMETER Prompt
    Search prompt for single-run mode.
.PARAMETER PromptFile
    YAML file with prompt for auto mode.
.PARAMETER Condition
    Filter by condition: new, used, refurbished, open_box, any.
.PARAMETER Category
    Filter by category: electronics, appliances, auto, any.
.PARAMETER Winners
    Override number of winners.
.PARAMETER Format
    Override output format: json, markdown, both.
.EXAMPLE
    .\scripts\run_once.ps1 --Prompt "DJI drone under 350 euros" --Condition refurbished --Category electronics
.EXAMPLE
    .\scripts\run_once.ps1 --PromptFile prompts/auto.yaml
#>

param(
    [string]$Prompt = "",
    [string]$PromptFile = "",
    [string]$Condition = "",
    [string]$Category = "",
    [int]$Winners = 0,
    [string]$Format = ""
)

$repoRoot = Split-Path -Parent $PSScriptRoot
cd $repoRoot

$args = @("python", "-m", "src.cli", "run")
if ($Prompt) { $args += @("--prompt", $Prompt) }
if ($PromptFile) { $args += @("--prompt-file", $PromptFile) }
if ($Condition) { $args += @("--condition", $Condition) }
if ($Category) { $args += @("--category", $Category) }
if ($Winners -gt 0) { $args += @("--winners", $Winners) }
if ($Format) { $args += @("--format", $Format) }

& $args
exit $LASTEXITCODE