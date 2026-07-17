# OPM — Session Handoff

_Last updated: 2026-07-08. Read this to resume cold. The condensed version also
lives in memory (`~/.claude/projects/-home-brandg-Documents/memory/opm-project.md`
+ `regime-preparedness.md` + `trading-account.md`) and auto-loads each session._

Project root: **`/home/brandg/Documents/OPM`**  ·  Python venv: `./.venv`  ·  Tests: `./.venv/bin/python -m pytest -q` (65 passing)

---

## 1. What OPM is
A long-only swing-trading support/resistance scanner for a personal **IBKR**
account. It ranks the most volatile S&P 500 names, detects S/R zones on daily
bars, scores them, builds long bracket setups in tradable support→resistance
corridors, and reports change-only alerts on a daily schedule.

**Constraints that shaped every decision:** long-only (for now); swing horizon
with **no intraday account access** (→ place GTC bracket orders before the open,
broker executes); small account (~$3.6k, possibly +$30k) using **fractional
shares**; user is methodical and wants honest numbers over flattering ones.

## 2. Status in one line
**All 7 build phases complete and deployed** (daily systemd timer). Now in the
**validation / paper-trade phase.** Honest net edge ≈ **+0.12 to +0.18 R/trade**.

## 3. The honest edge (and why it's not the headline number)
- Gross in-sample (full universe, 2,363 long trades): **+0.281 R/trade, PF 1.38**, 27% win rate, avg win +3.7R vs avg loss −1.0R (low-win-rate / big-winner profile).
- **Slippage** (0.05×ATR on stop/time market-order legs only; limit entry+target unaffected): → **+0.203 R** (PF 1.25). Config default now `slippage_atr: 0.05`.
- **Survivorship** (universe = *current* S&P members; crashed-out names missing): measurable part pulls gross toward ~+0.24R, plus an unquantifiable delisted-to-zero tail. Direction-only.
- **Out-of-sample** (`scripts/oos.py`): positive **every quarter** (+0.14 to +0.46R); first-half +0.354R vs second-half +0.207R (mild decay, still positive). The one tuned param (stop buffer) generalized — chasing train-optimal would have *hurt*.
- **Net realistic bar to plan against: ~+0.12–0.18R.** Positive, real, roughly half the gross headline. All still within **one bull-market year** (survivorship + no-bear-regime are the ceiling).

## 4. The pipeline (end to end)
1. **Volatility rank** — Wilder ATR% on daily bars (`src/volatility.py`), min_bars=100 guard drops thin-history spinoffs.
2. **Pivots** — fractal highs/lows, last N bars unconfirmed (`src/pivots.py`).
3. **Clustering** — greedy, anchored, **PRICE-RELATIVE** (merge threshold = tolerance × ATR% × price), 1-yr lookback window (`src/zones.py`).
4. **Scoring** — 6 components → 0-100 composite: touches, bounce, angle(V-shape), psych(round-number), containment(closes-not-wicks), recency (`src/scoring.py`).
5. **Trade construction** — nearest strong support below (with pullback-from-above guard) + resistance above; entry just above support, stop = support_low − 0.35×ATR, target just below resistance; gates: corridor ≥3%, R/R ≥2 (`src/trades.py`).
6. **Regime / cash switch** — synthetic equal-weight index vs 200d trend; below trend → suppress new longs ("cash mode"), shorts optional-but-off (`src/regime.py`).
7. **Change-only alerts** — per-symbol state machine (WATCHING/ARMED/FLAT), alerts on transitions only (`src/alerts.py`).

## 5. Hard-won design lessons (do NOT regress these)
- **Everything price-comparative must be price-relative, not fixed-dollar.** Bit us twice: zone clustering (MRVL "17× fat zone" bug) and bounce/angle scoring. Normalize by ATR% × price / by the pivot's own price.
- **Approach-direction guard** (the BRO bug): a zone below price only counts as *support* if price has been trading *above* it recently (pullback from above), not *rising into it from below* (that's resistance). ≥50% of last 15 closes above the zone.
- **Trend filter costs in-sample but the backtest is structurally BLIND to its value** — it protects against falling knives that keep falling, which are exactly the survivorship-excluded names. Left OFF by default (`require_trend: false`); it's a judgment tool, not a backtest-endorsed one.
- **Shorts lose in this sample (−0.055R) but that's REGIME-driven** (bull market); they flip positive in down-regimes (only 8 trades — unmeasurable). Wired but off (`regime.allow_shorts: false`). Reconsider as regime insurance, not standalone return.
- **Keep the stop TIGHT (0.35×ATR).** Widening it does NOT improve expectancy and slashes trade count (fails R/R gate). Backtester falsified the "widen it" intuition.
- **`max_hold_bars` now 10** (was 30), aligned to the user's 2-week horizon. Fresh sweep: 30→10 costs ~10% of NET edge on the full universe (+0.203→**+0.182R** net, PF 1.23, 2441 trades) — makes the backtest honest to actual behavior rather than measuring a 30-bar strategy the user doesn't run. (The old "~92%" note was optimistic; real haircut ~10–18%.) 15–20 bars keeps more edge if the horizon is ever treated as soft.
- **Slippage hits only the market-order legs** (stop, time). Limit entry + limit target take no adverse slippage.

## 6. How to operate it
**Automatic (deployed):** user systemd timer `opm.timer` runs `opm.service` →
`scripts/run_cycle.sh` every **weekday 18:30 ET** (America/New_York),
`Persistent=true` catch-up. It refreshes the yfinance cache then diffs & alerts.
- Logs: `journalctl --user -u opm` · `reports/alerts.log` (digest) · `reports/cron.log` (fetch).
- Manage: `systemctl --user {start,status,list-timers,disable} opm.timer` (needs `XDG_RUNTIME_DIR=/run/user/$(id -u)` in non-login shells).
- Catch-up fires at next login if machine was off; `loginctl enable-linger brandg` to fire while logged out.

**Manual commands (all from project root, via `./.venv/bin/python`):**
- `scripts/scan.py --armed-only --top 40 --save` → today's watchlist + CSV (`reports/watchlist_<date>.csv`).
- `scripts/backtest.py [--side long|short|both] [--require-trend] [--by-symbol]`.
- `scripts/sweep.py --param <section.key> --values a,b,c [--limit N]` → tune any config knob.
- `scripts/oos.py` · `scripts/regime_backtest.py` · `scripts/survivorship.py`.
- `scripts/paper_advance.py` (daily ledger step, in run_cycle) · `scripts/paper_report.py` (forward scorecard) · `scripts/seed_paper.py --csv <watchlist> --signal-date <d> --symbols A,B` (one-off seed).
- `scripts/plot_{volatility,zones,scores,setups}.py` → PNGs in `reports/`.
- Workflow: read the ARMED lines → place GTC bracket orders by hand in IBKR → hold to bracket.

## 7. Live trades in flight (started 2026-07-07)
User placed the top 4 from the 2026-07-07 watchlist "on a lark": **ARES, TXN, PH,
DOV.** Two stopped out fast, two recovered the loss (textbook for the 27%-win /
big-winner profile). Plan: **hold ~2 weeks, no discretionary changes** (keeps the
paper-trade data clean = first entries in task #2). NOTE: in later daily runs
these show as CLEARED/disarmed/watching — that's *setup* state, NOT a signal to
exit held positions.

## 8. Files map
- **src/**: `storage.py` (SQLite cache), `resolver.py` (symbol→IBKR contract), `ingest.py`, `volatility.py`, `pivots.py`, `zones.py`, `scoring.py`, `trades.py` (long + `build_short_setup`), `backtest.py` (walk-forward, side-aware, slippage), `trend.py`, `regime.py`, `alerts.py`.
- **scripts/**: scan, monitor, backtest, sweep, oos, regime_backtest, survivorship, fetch_yahoo, ingest_json, plot_*, run_cycle.sh.
- **config.yaml**: all tunables. **data/**: `scanner.db` (250k daily bars, 503 names), `sp500.txt`, `sp500_constituents.csv` (GICS sectors). **reports/**: PNGs, alerts.log, watchlist CSVs. **tests/**: 65 tests + fixtures.

## 9. Key config knobs (config.yaml)
`volatility.atr_period 20 / min_bars 100` · `pivots.n_bars 4` · `clustering.atr_tolerance 0.35` ·
`detection.lookback_bars 252` · `scoring.weights + params` · `trade.{min_corridor_pct 0.03,
min_reward_risk 2.0, stop_atr_buffer 0.35, min_zone_score 55, max_entry_dist_pct 0.03,
require_trend false, account_equity 3585, risk_pct 0.01, max_position_pct 0.25}` ·
`regime.{enabled true, sma_period 200, allow_shorts false}` ·
`backtest.{warmup_bars 252, max_hold_bars 10, slippage_atr 0.05, resignal_every 3}`.

## 10. Data source & runtime facts
- **Data:** yfinance bulk daily (matches IBKR to the cent; auto_adjust=False = split- but not dividend-adjusted). The **IBKR MCP tools** (get_price_history, search_contracts, create_order_instruction, get_account_summary) are only available in an **interactive Claude session**, not to standalone scripts — reserved for contract resolution + live quotes + execution.
- **Runtime decision (#3, DONE):** cron/systemd scan + MANUAL order placement. No daemon. GTC brackets mean the broker handles intraday execution, so live intraday quotes (#4) are largely moot. The `ib_async` one-shot bracket-placer (#5) is the "remove the manual step" upgrade for LATER (post-validation).
- **Environment note:** the working clock is 2026; yfinance/IBKR data are consistent with that. Account ~$3,585 net liq; 25% position cap currently binds every setup (only ~4 positions fit; `risk_pct` inert until account grows).

## 11. Open work (tasks) — recommended order
DONE: #1 out-of-sample · #2 forward paper ledger (BUILT) · #3 runtime decision · #7 slippage · #11 scheduling.
- **#2 (testing) Paper-trade — DONE (forward simulator, not IBKR paper).** `src/paper.py`
  replays the backtester's SAME fill/exit primitives one new bar at a time, persisting to
  a `paper_trades` table. Chose a self-built forward ledger over an IBKR paper account
  because (a) it kills overfit + survivorship (genuinely out-of-sample forward data),
  (b) it records EVERY armed signal, breaking the ~4-position N bottleneck a real/IBKR-paper
  account imposes, and (c) execution realism is already covered by the 4 real trades. Wired
  into `run_cycle.sh` after monitor. Seeded with ARES/TXN/PH/DOV from watchlist_2026-07-07;
  ledger independently reproduced reality (ARES/PH stopped, TXN/DOV open). Reports two views:
  UNCONSTRAINED R-edge (validation stat) + CONSTRAINED ≤4-position $ P&L (closes the
  portfolio-sim caveat #4). Now accrues passively; let it run and check `paper_report.py`.
  Files: `src/paper.py`, `scripts/paper_advance.py`, `scripts/paper_report.py`,
  `scripts/seed_paper.py`, `tests/test_paper.py` (9 tests, incl. paper-R == backtest-R invariant).
- **#5 (structural) one-shot `ib_async` bracket-placer** — the automation upgrade, after edge validates.
- **#6 wire live IBKR net_liq + revisit position cap** (esp. if +$30k lands).
- **#8 wide-corridor / target-reachability — DONE.** ATR-normalized `target_dist_atr`
  + optional off-by-default gate `trade.max_target_atr`. Sweep showed the gate is NOT an
  edge lever (far targets already time-stop honestly; +0.22R on/off) — it's a DISPLAY fix
  for manual picking. scan shows `tATR` col + `far` flag (>12); use tATR NOT corridor_pct
  (the latter over-flags volatile names: FIX 18% corridor is only 2.9 ATR = reachable;
  WBD 36.7 ATR = truly illusory). `src/trades.py`, `scripts/scan.py`, `scripts/sweep.py`
  (now accepts `null` baseline), `tests/test_trades.py`.
- **#9 complete short side** (fix short sizing; surface shorts in scan/monitor).
- **#10 detection refinements** (blue-sky ATR target; adjacent-zone merge).
- **#12–#15 test coverage** (monitor integration; cash/short-mode; short-setup unit tests; recurring data-hygiene).
- **#16 point-in-time/delisted survivorship test** (needs data we can't get cleanly; standing caveat).
- **#4 intraday quotes** — largely moot given GTC brackets; keep only for a true 30-min loop.
- **Possible new task:** position-aware monitor (separate "new setup gone" from "status of what you hold").
- **RESOLVED:** `max_hold_bars` set 30 → 10 to match the 2-week horizon (~10% net-edge haircut; honest to actual behavior). Also affects the paper ledger's time-stop.

## 12. Gotchas / things future-me should not trip on
- Memory files auto-load; this handoff is the full read. Project is **OPM** (renamed from `sr-scanner` on 2026-07-08).
- The **monitor tracks SETUP state, not POSITIONS** — CLEARED/disarmed ≠ "exit your trade."
- Daily churn is high on down days (dip-buyers rotate with the tape) — expected; watch whether flat days churn hard too (would suggest loosening the 3% armed window).
- After any folder move, `./.venv/bin/python` still works (derives prefix from its own location); the shebang'd console scripts would break, so always use `python -m`.

**EMAIL DIGEST LIVE (2026-07-17):** the daily monitor now emails the actionable
ARMED/CLEARED digest (src/notify_email.py, ported from Carmen; change-only; flags
far-target rows). Enabled in config; creds in `~/.config/opm.env` (chmod 600, sourced
by run_cycle.sh) — on Windows set OPM_SMTP_USER/OPM_SMTP_PASSWORD as user env vars.
Test send verified to brandg@gmail.com. This is the first (outbound-only) slice of the
[[opm-automation-roadmap]]. 80 tests.

**MIGRATION IN PROGRESS:** moving from the Pop!_OS laptop to the Windows 11 desktop
(cutover planned Saturday 2026-07-18) — see **MIGRATION.md** for the full checklist.
Laptop prep done 2026-07-15: git repo initialized, `scripts/run_cycle.ps1` ported
(Task Scheduler replaces the systemd timer). Key rules: transfer `data/scanner.db`
separately (gitignored; holds the paper ledger), never run the daily cycle on both
machines (forks the ledger), disable the laptop's `opm.timer` at cutover. Backups
(user has none!) are the first post-cutover task.

_Next up per the user: a new project (name TBD, teased as even better than "OPM" = Other People's Money)._
