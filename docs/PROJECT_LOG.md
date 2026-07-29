---
name: opm-project
description: "Goals, constraints, and locked design decisions for the OPM S/R swing scanner"
metadata: 
  node_type: memory
  type: project
  originSessionId: d7ef917e-4cf1-4076-a16c-cfedc53b2b96
---

Project at `/home/brandg/Documents/OPM`: a long-only swing-trading
support/resistance scanner over the volatile end of the S&P 500. Started
2026-07-07. Pipeline: rank by ATR% (daily bars) → fractal pivots → ATR-normalized
zone clustering → zone scoring (touches, V-shape, psychological, containment,
recency) → support→resistance corridor filter → fractional-share trade
construction (entry just above support, stop = support_zone_low − ~0.35×ATR NOT
next support down, target just below resistance, hard R/R ≥ 2 gate) → 30-min
state-machine reporter → IBKR bracket execution.

Locked decisions:
- **Data source (revised):** bulk daily bars for the whole universe come from
  **yfinance** (free, symbol-keyed, matches IBKR to the cent on AMD — verified;
  use auto_adjust=False = split-adjusted but not dividend-adjusted, which is what
  we want for S/R levels). IBKR (session MCP now, `ib_async` later) is reserved
  for contract resolution + live quotes + execution on the handful of surviving
  names. `get_price_history` needs a numeric `contract_id`, not a ticker;
  `search_contracts` is noisy (941 rows for "KO") so the resolver filters to
  exact-symbol + US-primary.
- **Storage re-keyed by symbol** (was contract_id): symbol is the analysis
  identity; contract_id is an execution detail stored nullable on the symbols
  table, resolved lazily. Bulk source populated via scripts/fetch_yahoo.py.
- **Detection timeframe:** daily bars for v1 (not 5m/15m — all advisors agreed).
- **Sizing:** fractional shares (account too small for whole shares of $500 names).
- **Backtester before live scanner**; execution is full intraday automation as the
  end state but only after the backtest shows an edge.
- **Storage:** source-agnostic local SQLite cache is the single source of truth
  every stage reads from.

Open items: (1) **Runtime not decided** — standalone `ib_async`+IB Gateway daemon
vs a scheduled Claude agent using MCP; deferred because nothing in the math
depends on it. (2) **Split/adjustment status of IBKR daily history unverified** —
must check `include_corporate_actions` against a known recent splitter before
trusting historical levels. (3) Symbol→contract_id resolution is noisy (119
global matches for "AMD"); resolver picks US-primary common stock, results cached.

Phases 1-2 done and tested (19 passing tests). Full universe LIVE: all 503 S&P
500 names in data/sp500.txt (+ sectors in data/sp500_constituents.csv), populated
with 2yr daily bars via yfinance (~250k bars). Ranker has a min_bars=100 guard
that excludes thin-history spinoffs (HONA 15 bars, FDXF 28) and reports them
rather than dropping silently. Full-universe top vol is semis/storage/optical
(SNDK, SMCI, COHR, LITE, MRVL, TER, WDC, MU, INTC...). Bottom includes merger-arb
names (EA ~0.45% — pending take-private) — expected, correctly filtered out.
Visual proof: scripts/plot_volatility.py --top N -> reports/phase2_*.png.

Phase 3 (pivots + clustering) DONE and passed the chart-validation gate (29
tests). src/pivots.py (fractal, strict, last n bars unconfirmed), src/zones.py
(greedy anchored clustering). KEY FIX found via the gate: clustering must be
PRICE-RELATIVE, not fixed-dollar — merge threshold = tolerance * ATR% (ATR/price)
via (price-anchor)/anchor <= tol_frac. A single absolute tolerance*ATR over a
long trending history over-merged old low-priced pivots into fat zones (MRVL
"17x" bug). Also added detection.lookback_bars=252 (~1yr window) for relevance +
representative ATR; full history stays cached for backtest. Validated on
SMCI/MRVL/AMD/ORCL/KO/JNJ -> reports/phase3_zones.png via scripts/plot_zones.py.

Carry into Phase 5: blue-sky breakouts (AMD $516) have NO overhead resistance —
target logic must handle "no S/R above" (skip or ATR-projected target). Minor:
adjacent same-kind zones could use a light second-pass merge.

Phase 4 (zone scoring) DONE (35 tests). src/scoring.py: 6 sub-scores in [0,1]
combined by config weights (sum 100) -> 0-100 composite. touches(log/cap),
bounce(rejection reach), angle(min(in,out) V-shape), psych(round-number, price-
scaled, boost-only), containment(held/(held+broke) using CLOSES not wicks),
recency(exp decay on bars since last touch). Params in config scoring.params.
Same price-relative lesson applied AGAIN: bounce/angle normalize the move as a
fraction of the PIVOT's own price scaled by ATR% (not dollars/current-ATR), else
old low-priced bounces get crushed (MRVL base 54->70 after fix). Reports:
scripts/score.py (text breakdown) + plot_zones now shades by score. Scores spread
~45-75, discriminate well; strongest = heavily-touched + recent + clean rejection.

Phase 5 (corridor filter + trade construction) DONE (41 tests). src/trades.py:
find_bracketing_zones (nearest strong support below / resistance above, score >=
min_zone_score), build_setup (entry=support_high+0.05ATR, stop=support_low-0.35ATR,
target=resistance_low-0.10ATR, gates: corridor>=3%, R/R>=2, blue-sky=skip),
size_position (fractional, risk 1% capped at 25% equity). scripts/scan.py scans
full universe in ~3.6s -> ranked setups; scripts/plot_setups.py overlays
entry/stop/target. Bracket geometry validated visually (reports/phase5_setups.png).

Split-adjustment concern CLOSED: cache audit found only 6 >60% overnight jumps,
all real earnings crashes (FISV/DXCM/CNC/TTD/WST), no unadjusted splits; NFLX/
AVGO/ROP cached == fresh yfinance. (Those crashes = the gap risk motivating an
earnings filter.) Small-account reality: position cap (25%=$896) binds on EVERY
setup, so risk_pct is currently inert and only ~4 positions fit.

Refinements for Phase 6/7 (found via plot_setups, not bugs): (1) NO trend filter
-> buys support in downtrends (BRO knife-catch); add ADX/Choppiness gate.
(2) Wide-corridor targets are stale far-away levels (ROP 41% corridor, illusory
R/R 34.8); add max-corridor cap or target-reachability (within N*ATR) check.

Phase 6 (BACKTESTER) DONE (52 tests). src/backtest.py: walk-forward, NO look-ahead
(re-detect from df.iloc[:i+1] each signal), buy-limit entry fills on pullback
(gap-aware), exits target/stop/time-stop, edge in R-multiples (sizing-independent).
scripts/backtest.py (full run) + scripts/sweep.py (tune any config param).
Full-universe BASELINE: 2363 trades, win 27.4%, expectancy +0.281R/trade, PF 1.38,
+663R, stopped-then-recovered 50%, avg hold 2.8 bars.

KEY FINDING (settles the deferred stop question): swept stop_atr_buffer 0.35..2.0.
Widening the stop does NOT improve per-trade expectancy (stays ~+0.17-0.30, noise)
and slashes trade count (701->26 at 150-sym subset) because wider stop -> lower R/R
-> fails R/R>=2 gate. Tight 0.35 stop wins on TOTAL edge (+204R vs +7R). So: KEEP
stop tight (0.35); the 50-54% noise-stop rate is fine because big winners pay for it.
Backtester falsified the "widen the stop" intuition.

CAVEATS not yet modeled (do before trusting live): (1) NO transaction costs/slippage
- ~0.28R gross may thin to ~0.15-0.25R net (commissions + entry/exit slippage on a
small account). (2) SURVIVORSHIP BIAS - universe = CURRENT S&P 500 members; dropped/
crashed names excluded, inflates results. (3) IN-SAMPLE only - no train/test split;
tuning risks overfit. (4) portfolio sim not done (per-trade R only; ignores 4-position
cap + capital).

SHORT SIDE measured (src/trades.py build_short_setup, backtest side-aware, 58 tests).
Full universe: LONG +0.281R/PF1.38/+663R; SHORT -0.055R/PF0.93/-148R (LOSES);
COMBINED +0.102R (diluted); long-vs-short monthly-R corr +0.07 (NOT a hedge).
Conclusion: shorting HURT over this 2yr BULL sample and gave no hedge. BUT two
asterisks cut the other way: (a) bull-market sample - shorts are counter-cyclical
insurance for a regime we can't see here; (b) survivorship UNDERSTATES shorts (the
delisted crashers that would be short wins are missing). So: don't add shorts for
return now; reconsider as regime insurance later. User willing to add $30k (enables
margin/shorts) but data says no rush.

TREND FILTER (src/trend.py, trade.require_trend, slope-of-SMA def NOT close>SMA
because dip-buys enter below the MA). Result: HURTS measured long edge (+0.281 ->
+0.237R, removes 40% of trades; the REMOVED trades averaged +0.345R - it drops the
BEST trades). KEY META-INSIGHT: the backtest is structurally BLIND to the trend
filter's purpose - it protects against falling knives that keep falling, which are
exactly the survivorship-EXCLUDED names (crashed out of index). Our data only has
knives that bounced. So low in-sample value != useless; it's un-measurable here.
Trend filter left OFF by default (backtest says it costs edge) but kept available
as risk insurance; its true value needs point-in-time/delisted data to measure.

Phase 7 (scheduler/state-machine/alerts) DONE (65 tests). src/alerts.py: change-only
state machine (WATCHING/ARMED/FLAT; alerts on transitions only, no spam; re-alerts on
changed support zone). storage.py: setup_state table + meta (get/set) for persistence
across runs. scripts/monitor.py: regime banner + cash gate + per-symbol diff -> alert
digest to reports/alerts.log; ARMED/CLEARED are actionable, NEW_WATCH/DISARMED info.
Regime-flip alerts via stored last_regime. scripts/run_cycle.sh: refresh cache + monitor,
cron-ready (daily post-close = right cadence for no-intraday-access -> place GTC brackets
pre-open). Verified: 1st run = all-armed fire once; 2nd run = "no changes". NOTE: runs off
cached daily bars; a true intraday 30-min loop needs a live-quote refresh wired into
monitor.py (deferred with the runtime A/B decision). See [[regime-preparedness]].

All 7 phases complete. Remaining work tracked as tasks #1-16 (structural + testing).

OUT-OF-SAMPLE CHECK done (task #1, scripts/oos.py). PASSED within data limits:
edge positive in EVERY full quarter (+0.14 to +0.46R), first-half +0.354R vs
second-half +0.207R (both positive, MILD decay toward present). Overfitting test:
tuned stop_atr_buffer on train half -> best-on-train was 0.75 but it gave WORSE OOS
(+0.265R) than the default 0.35 (+0.341R, also best-on-test). I.e. keeping 0.35
(our Phase-6 restraint) generalizes; chasing train-optimal would have hurt. BUT this
is OOS across sub-periods of ONE bull year (252-bar warmup eats year 1, signals only
~2025-07..2026-07) — confirms in-regime stability, NOT cross-regime; survivorship +
no-costs caveats still stand. Next recommended: paper-trade (#2) or slippage (#7).
See [[trading-account.md]].

SLIPPAGE HAIRCUT done (task #7, backtest.slippage_atr, applied ONLY to stop/time
market-order exits; limit entry+target unaffected). Full-universe re-baseline:
gross +0.281R -> 0.05ATR +0.203R (PF1.25) -> 0.10ATR +0.125R. Config default set to
0.05 (net-by-default; reversible; doesn't affect live scan). HONEST NET EDGE after
stacking slippage + measurable survivorship ~ +0.12 to +0.18R (plus unquantifiable
delisted tail) — about half the gross headline. Still positive; paper-trade against
THIS bar, not +0.28. Tasks #1 (OOS) + #7 (slippage) now done; #2 paper-trade next.

RUNTIME DECISION (#3) DONE: chose cron scan + MANUAL order placement (no daemon).
Rationale: GTC bracket orders + no intraday access means the broker executes
intraday for you -> no always-on process and no live intraday quotes needed (#4
largely moot; #5 reframed to a one-shot ib_async bracket-placer for LATER, post-
validation). Scheduling (#11 done): switched from cron to a USER SYSTEMD TIMER with catch-up.
Units: ~/.config/systemd/user/OPM.{service,timer}; OnCalendar=Mon-Fri 18:30
(America/New_York), Persistent=true (runs missed job on next boot/login),
RandomizedDelaySec=120. Enabled via `systemctl --user enable --now OPM.timer`;
old crontab line removed. Service validated green under systemd (Result=success).
Logs: `journalctl --user -u OPM` + reports/alerts.log (digest) + reports/
cron.log (fetch). CAVEAT: without `loginctl enable-linger brandg`, the user manager
runs at login, so catch-up fires at next login (fine for a daily desktop); enable
linger if you want it to fire while logged out / immediately at boot. NOTE: monitor tracks SETUP state, not POSITIONS — its CLEARED/
disarmed lines mean "no longer a NEW-entry setup / cancel unfilled entry limits",
NOT "exit your held position". Possible future task: position-aware monitor.

MAX_HOLD_BARS aligned 30 -> 10 (user's real 2-week horizon). Fresh full-universe sweep:
30->10 costs ~10% of NET edge (+0.203 -> +0.182R net, PF 1.23, 2441 trades); the old
"~92% of edge" note was optimistic (real haircut ~10-18%). Rationale: config should
measure the strategy actually run, not a 30-bar one the user won't hold to. +0.182R is
now the honest bar. 15-20 bars keeps more edge if the horizon is ever soft. NOTE this
also drives the paper ledger's time-stop (paper reads backtest.max_hold_bars).

WIDE-CORRIDOR / TARGET-REACHABILITY (#8) DONE. Added an ATR-NORMALIZED reachability
metric `target_dist_atr = (target-entry)/atr` (not corridor_pct — same price-relative
lesson) to build_setup/build_short_setup + optional hard gate `trade.max_target_atr`
(reason "target_unreachable"). KEY FINDING (backtest falsified the intuition, like the
trend filter): sweeping the gate 6..20 ATR changed edge by NOTHING (exp +0.22R, PF 1.28
on/off) — far targets already time-stop honestly in the backtester, so the wide-corridor
problem is a DISPLAY/RANKING illusion for MANUAL selection, not an edge leak. So gate left
OFF by default; the value is surfacing the metric. scan.py now shows a `tATR` column + " far"
flag (>12) and CSV carries target_dist_atr. IMPORTANT correction: tATR separates genuinely-far
targets (WBD tATR 36.7/rr 77.8, ABT 13.8, PODD 14.4 = illusory) from high-corridor-but-
REACHABLE volatile names (FIX 18% corridor but only 2.9 ATR, ORCL 27% but 3.9 ATR — their
big R/R comes from TIGHT STOPS, not far targets, and IS legit). corridor_pct over-flags
volatile names; use tATR. Only ~6/215 passed setups trip tATR>12. 75 tests.

PAPER TRADE (#2) DONE as a SELF-BUILT FORWARD LEDGER, not an IBKR paper account.
Decision (user agreed): a forward simulator kills overfit+survivorship (out-of-sample
forward data), records EVERY armed signal (breaks the ~4-position N bottleneck that
caps a real/IBKR-paper account), and execution realism is already covered by the 4
real trades (delay negligible on these volatile names). src/paper.py replays the
backtester's SAME primitives (_ops/_exit_on_bar/apply_slippage/r_multiple — refactored
out of backtest._close so paper-R == backtest-R, locked by a test) ONE new bar at a
time, persisting to a paper_trades table (gap-safe last_processed_date cursor -> idempotent,
systemd-catch-up safe). scripts/paper_advance.py (in run_cycle.sh after monitor; regime-
aware, records nothing in cash mode), scripts/paper_report.py (UNCONSTRAINED R-edge vs the
+0.12–0.18R bar + CONSTRAINED ≤4-position $ P&L = closes portfolio-sim caveat #4),
scripts/seed_paper.py (one-off). 74 tests (was 65). Seeded ARES/TXN/PH/DOV from
watchlist_2026-07-07; ledger independently reproduced reality (ARES/PH stopped, TXN/DOV
open, TXN gap-filled at 288 open vs 292.67 limit). Now accrues passively — just let the
daily timer run and read paper_report.py periodically. See [[trading-account]].

SIZING GAP FIXED (found the hard way, 2026-07-29). LITE armed 2026-07-28 at score 82.5
(entry 654.57 / stop 616.11 / target 768.51, R/R 2.96) and stopped out next morning for
a real -$122. Post-mortem found a REPORTING defect, not a strategy one: build_setup has
always returned shares/position_value/risk_dollars/position_capped, but alerts.evaluate()
copied a fixed key tuple that omitted them, so the digest never showed size. The system
sized LITE at 2.652 sh / $102 risk; the order actually placed was 3.15 sh — ~19% oversized,
which is the whole gap between the modelled -1R and the realised -$122. Fix: alerts.py
carries the four sizing keys into the event, format_event appends "N sh ($X risk)", and
notify_email adds Shares + Risk columns (ⓒ marks size limited by the position cap rather
than by risk) with footer text saying the quantity IS the risk control. 81 tests pass;
Monday's alert re-rendered from cached bars to confirm. LESSON: a number computed but not
surfaced is a number the human guesses at.

FALLING-KNIFE GATE FALSIFIED (2026-07-29), the third intuition the backtester has killed
(after widen-the-stop and max-target-ATR). Motivating question: LITE was -27.7% over 42
bars and -38.1% off its 60-bar high at signal — "clearly trending down, why buy it?"
Tested as hard entry gates over the full 501-symbol universe (2547 long trades, base
+0.192R / PF 1.24 / win 29.6%): 42-bar return <= -10/-20/-30%, 21-bar <= -10/-20%, 60-bar
drawdown <= -15/-25/-35%, and 50-day SMA-slope-down. EVERY variant was neutral-to-harmful.
The aggressive ones cut edge hard (sma50 +0.121R on 333 trades; ret42<=-10% +0.114R —
because the -10%..-20% pullback bucket is the single BEST cohort, n=318, +0.443R, bootstrap
95% CI [+0.117,+0.843], P(mean>0)=1.00). Buckets LITE itself fell into ARE negative
(ret42 [-30%,-20%): n=57, -0.168R, only 14% reached target vs 24% baseline; dd60<=-35%:
n=16, -0.091R) — so the intuition is directionally defensible — but the bootstrap CIs
span zero ([-0.577,+0.270] and [-0.789,+0.731]) and the ADJACENT deeper bucket flips to
+1.228R (n=10), which is the signature of noise, not a threshold. A gate tuned to block
LITE exactly (ret42<=-20% AND dd60<=-35%) blocks 11 of 2547 trades worth +1.4R and moves
edge by +0.0003R: not a lever. Inverse finding worth more: EXTENDED names are the real
dead zone (ret42 >= +10%: n=265, +0.012R; >= +25%: n=23, -0.187R) — this strategy wants
moderate pullbacks, and buying strength is where its edge actually vanishes.
CAVEAT (same structural blindness as the trend filter): survivorship. The knives that kept
falling are delisted and absent, so this test SYSTEMATICALLY UNDERSTATES knife risk and
cannot settle the question — it can only say the gate is unjustified ON MEASURABLE DATA.
Left OFF. If added later, justify it as variance/ruin control on a small account, not as
expectancy. Scripts kept in scratchpad (knife_test.py / knife_slice.py), not promoted.

SIZING DECISION (2026-07-29): user switched real orders from a self-imposed fixed
~$2,000 notional to the system's printed share count. IBKR fills showed 13 of the last
22 buys sat in $1,900-$2,100 regardless of stop distance. CORRECTION TO MY OWN FIRST
NUMBER, worth recording because it changed the recommendation's size: I initially
measured risk-sizing as worth ~2x ($342 vs $156 over 188 closed ledger trades) using a
25% position cap — but trade.max_position_pct is 0.20. Redone correctly: $177 vs $156,
only **+13%**. The reason is structural: the 20% cap ($2,040) BINDS ON 99% OF SETUPS
(186/188), so OPM's "risk-based" sizing is already fixed-dollar in practice and risk_pct
is largely inert — median ACTUAL risk per trade is ~$36 against an intended flat $102
(range $7-$102). This re-confirms the Phase-5 note that the position cap makes risk_pct
inert; it is now quantified. So the switch is VARIANCE CONTROL, not an edge upgrade: it
only bites on the rare wide-stop name where the risk calc lands under the cap. LITE was
exactly that case (wanted $1,736 / 2.652sh; the $2,062 actually bought = ~19% oversized,
and $122 lost vs $102 intended). Nice consequence: risk-based sizing automatically bets
LESS on volatile wide-stop knives — i.e. it delivers the falling-knife protection that
the falling-knife GATE could not justify on the data. OPEN, not yet raised with user:
raising max_position_pct would make risk_pct live again but conflicts with holding ~5
concurrent positions on a $10k account. Live net liq checked: $10,079.89 vs config
10,200 (1.2% off, immaterial). NOTE buying power was only $2,090 with $6,043 cash —
unsettled T+1 proceeds; that, not sizing, is what limits new positions the next morning.

DECLINE CONTEXT SURFACED (2026-07-29, reporting only). Since the knife gate could not be
justified but the user still wants to eyeball trend, added trades.decline_metrics(closes)
-> ret_42b (~2-month return) + dd_60b (drawdown off the 60-bar high), carried through
alerts.evaluate into a "2mo" email column, red at <= -20%, footer says explicitly it is
context and not a filter. Deliberately mirrors the target_dist_atr posture: SURFACE the
metric, do not gate on it. Re-rendered 2026-07-28 from cache as a check — LITE reads
"2.652 sh / $102 / -28% (-38% off hi)" and BLDR "27.7214 sh ⓒ / $54 / -5% (-19% off hi)",
which shows the point at a glance: LITE was the steep-decline name AND carried double
BLDR's dollar risk. 84 tests (was 81), incl. one asserting a steep decline does NOT block
an otherwise-passing setup, so the no-gate posture can't regress silently.
