# One scan cycle (Windows port of run_cycle.sh): refresh the daily-bar cache,
# diff & alert on changes, then advance the forward paper ledger.
# Intended cadence: once per weekday after the close -> place GTC brackets
# before the next open.
#
# Scheduled by Windows Task Scheduler (see MIGRATION.md):
#   Action:  powershell.exe -NoProfile -ExecutionPolicy Bypass -File "<repo>\scripts\run_cycle.ps1"
#   Trigger: weekly Mon-Fri, evening local time (safely post-close year-round)
#   Enable:  "Run task as soon as possible after a scheduled start is missed"
#            "Wake the computer to run this task"
#
# Written for Windows PowerShell 5.1 (Task Scheduler's default) - no PS7-isms.

$ErrorActionPreference = "Stop"

# Project root = parent of this script's directory (equivalent of cd "$(dirname "$0")/..")
Set-Location (Split-Path -Parent $PSScriptRoot)

New-Item -ItemType Directory -Force -Path reports | Out-Null

$py = Join-Path ".venv\Scripts" "python.exe"

# set -e equivalent: native commands don't trip $ErrorActionPreference in PS 5.1,
# so check $LASTEXITCODE after each step explicitly.
& $py scripts\fetch_yahoo.py --period 2y *>> reports\cron.log
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

& $py scripts\monitor.py --quiet-if-empty
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

# Forward paper ledger: advance live trades on the fresh bars, record today's
# armed setups. Passive validation - accrues the honest forward edge over time.
& $py scripts\paper_advance.py --quiet
exit $LASTEXITCODE
