<# 
.SYNOPSIS
    Install scheduled tasks for Auto Deal Searcher.
.DESCRIPTION
    Creates Windows Task Scheduler entries for each enabled schedule task.
#>

$repoRoot = Split-Path -Parent $PSScriptRoot
cd $repoRoot

python -m src.cli schedule-install