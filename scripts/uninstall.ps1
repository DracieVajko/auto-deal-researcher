<# 
.SYNOPSIS
    Uninstall scheduled tasks for Auto Deal Searcher.
.DESCRIPTION
    Removes all Windows Task Scheduler entries for Auto Deal Searcher.
#>

$repoRoot = Split-Path -Parent $PSScriptRoot
cd $repoRoot

python -m src.cli schedule-uninstall