# OPM: Pop!_OS laptop → Windows 11 desktop migration

_Cutover planned Saturday 2026-07-18. Prep done on the laptop 2026-07-15 (git repo
initialized, `scripts/run_cycle.ps1` ported, this checklist). Work through in order;
each phase gates the next._

## Why the desktop
The daily 18:30 job needs a machine that's reliably on. Task Scheduler can also
**wake the desktop from sleep** to run the job — an upgrade over the laptop.

## Do-anytime prep (any evening BEFORE Saturday)
Everything stateless can happen early — only ledger ownership (fresh `scanner.db`
+ which machine's timer runs) defines the cutover. Safe now, on the desktop:
- [ ] Install **Python 3.12** (python.org, check "Add python.exe to PATH" —
      Win11 ships only a Store stub, not real Python).
- [ ] Install **Git for Windows** (defaults are fine).
- [ ] Install **Claude Code** for Windows and sign in.
- [ ] Install **TWS** for Windows + configure API settings (Phase 3 below). Note:
      logging in kicks the laptop's TWS session — harmless; the daily cycle
      doesn't use TWS.
- [ ] **Dress rehearsal (optional but recommended):** transfer the repo now, build
      the venv, run the 75 tests, copy a THROWAWAY `scanner.db`, and even run
      `run_cycle.ps1` manually against it. Treat that DB as disposable — it will
      be stale by Saturday and MUST be replaced with a fresh copy at cutover.
      The laptop remains the system of record until the timers flip.
- [ ] Create the Task Scheduler job (Phase 4) but leave it **DISABLED**.

If the rehearsal is done, Saturday reduces to: re-copy fresh `scanner.db` →
enable the desktop task → disable the laptop timer → verify one run.

## Phase 0 — Before leaving the laptop
- [ ] `cd ~/Documents/OPM && ./.venv/bin/python -m pytest -q` → **75 passed**
- [ ] Make sure no scan is mid-run, then grab a clean copy of **`data/scanner.db`**
      (25MB). It is gitignored on purpose — transfer it separately. It holds the
      **forward paper ledger** (irreplaceable validation evidence), setup state, and
      regime memory. Bars alone could be refetched; the ledger cannot.
- [ ] Transfer the repo: `git clone` over the network, or zip **excluding `.venv/`**
      (Linux binaries, useless on Windows) — e.g. `git archive` or copy the checkout.
- [ ] Optional: copy `reports/` for alert/watchlist history (also gitignored).
- [ ] Copy the Claude memory dir for a warm start on the desktop:
      `~/.claude/projects/-home-brandg-Documents/memory/` → same relative location
      under the desktop's Claude install. (`session_handoff.md` travels in-repo.)

## Phase 1 — Python environment (desktop)
- [ ] Install **Python 3.12** from python.org (check "Add python.exe to PATH").
- [ ] In the repo root (PowerShell):
      ```
      py -m venv .venv
      .venv\Scripts\python -m pip install -r requirements.txt
      .venv\Scripts\python -m pytest -q
      ```
- [ ] **GATE: 80 passed.** Do not proceed until green.
- [ ] Email digest creds: set the two SMTP env vars as **user** environment
      variables (so the scheduled task inherits them) — in PowerShell:
      `setx OPM_SMTP_USER "<gmail>"` and `setx OPM_SMTP_PASSWORD "<app-pw>"`
      (values are in the laptop's `~/.config/opm.env`). No opm.env file on Windows;
      `run_cycle.ps1` reads them from the environment. Verify: after a new shell,
      `echo $env:OPM_SMTP_USER` shows the address.
- [ ] Drop `scanner.db` into `data\` and sanity-check:
      `.venv\Scripts\python scripts\paper_report.py` → ledger prints with the
      open book intact.

## Phase 2 — Manual cycle run
- [ ] `powershell -NoProfile -ExecutionPolicy Bypass -File scripts\run_cycle.ps1`
- [ ] Compare the tail of `reports\alerts.log` against the laptop's for the same
      day — should be equivalent (a "no changes" run is fine).
- [ ] Note: running the cycle on BOTH machines against separate DB copies **forks
      the paper ledger**. One parallel comparison day max, then cut over.

## Phase 3 — TWS + API (desktop)
- [ ] Install TWS for Windows; log in (this kicks any laptop TWS session — IBKR
      allows one live login).
- [ ] Global Configuration → API → Settings: **Enable ActiveX and Socket Clients**;
      port **7496**; **localhost only** checked; **Read-Only API checked** (we are
      not placing orders programmatically yet).
- [ ] `.venv\Scripts\python scripts\check_api.py` → account summary prints.

## Phase 4 — Task Scheduler (the systemd-timer replacement)
- [ ] Task Scheduler → Create Task (not "Basic"):
  - General: "Run whether user is logged on or not"; run as your user.
  - Trigger: **Weekly, Mon–Fri**, evening local time. Pick a time that is safely
    after 16:00 ET year-round given the desktop's timezone (the job just needs
    post-close, pre-open — precision doesn't matter, DST drift does).
  - Action: `powershell.exe` with arguments:
    `-NoProfile -ExecutionPolicy Bypass -File "C:\<path-to-repo>\scripts\run_cycle.ps1"`
  - Settings: ✅ **"Run task as soon as possible after a scheduled start is missed"**
    (the `Persistent=true` equivalent) · ✅ **"Wake the computer to run this task"**.
- [ ] Power Options → Sleep → **"Allow wake timers" = Enabled**, or wake-to-run
      silently does nothing.
- [ ] Right-click the task → **Run** once manually; check `reports\alerts.log` and
      Last Run Result = 0x0.
- [ ] Let it fire once on schedule before trusting it.

## Phase 5 — Cutover (makes the desktop the system of record)
- [ ] On the laptop: `systemctl --user disable --now opm.timer` (and verify:
      `systemctl --user list-timers | grep -i opm` → nothing).
- [ ] Laptop becomes dev-only. Its `scanner.db` is now stale — never run the cycle
      there again without re-syncing the DB from the desktop first.
- [ ] Update `session_handoff.md` (project root = new Windows path).

## Phase 6 — Post-cutover (next session)
- [ ] **Backups** (task #9): private GitHub remote for the repo + a scheduled copy
      of `scanner.db`; then the user's broader no-backup situation.
- [ ] Longer-term: IB Gateway instead of TWS for the always-on daemon
      (see the automation roadmap).

## Rollback
Nothing on the laptop is destroyed by this plan — the systemd units and venv stay
in place (disabled). If the desktop misbehaves, `systemctl --user enable --now
opm.timer` on the laptop and copy the newest `scanner.db` back.
