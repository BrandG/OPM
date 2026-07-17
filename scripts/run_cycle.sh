#!/usr/bin/env bash
# One scan cycle: refresh the daily-bar cache, then diff & alert on changes.
# Intended cadence: once per weekday after the close (you can't act intraday, so
# EOD -> place GTC brackets before the next open is the right workflow).
#
# Scheduled by a user systemd timer (weekday 18:30 America/New_York, with catch-up):
#   ~/.config/systemd/user/opm.timer -> opm.service -> this script.
#   Manage: systemctl --user {start,status,list-timers,disable} opm.timer
#
# For a true intraday 30-min loop, wire a live-quote refresh into monitor.py
# (see the NOTE there) and schedule this every 30 min during RTH instead.
set -euo pipefail
cd "$(dirname "$0")/.."

# Load SMTP creds for the email digest (optional — monitor stays silent if absent).
set -a; [ -f "$HOME/.config/opm.env" ] && . "$HOME/.config/opm.env"; set +a

mkdir -p reports
./.venv/bin/python scripts/fetch_yahoo.py --period 2y >> reports/cron.log 2>&1
./.venv/bin/python scripts/monitor.py --quiet-if-empty
# Forward paper ledger: advance live trades on the fresh bars, record today's
# armed setups. Passive validation — accrues the honest forward edge over time.
./.venv/bin/python scripts/paper_advance.py --quiet
