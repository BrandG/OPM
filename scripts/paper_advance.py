"""Daily forward paper-ledger step: advance live trades, then record new signals.

Runs once per weekday after the close (wired into run_cycle.sh, right after the
monitor). Two phases, in this order:

  1. ADVANCE  — walk every PENDING/OPEN paper trade through the bars that have
                arrived since it was last seen (fills, exits, expiries).
  2. RECORD   — open a PENDING trade for each armed setup in today's scan we're
                not already in. Regime-aware: in cash mode we record nothing
                (same suppression the live strategy applies), so the ledger
                measures the strategy we actually run, not a different one.

Idempotent: re-running the same day advances nothing new and re-records nothing
(the dedup guard + the per-trade cursor both no-op).

Usage:
    python scripts/paper_advance.py [--config config.yaml] [--quiet]
"""

import argparse
import csv
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.storage import Store
from src.zones import detect_zones
from src.scoring import score_zones
from src.trades import build_setup, build_short_setup
from src.trend import trend_state
from src.regime import build_market_index, regime_series
from src.paper import advance_all, record_setups


def load_sectors(path: str) -> dict:
    p = Path(path)
    if not p.exists():
        return {}
    return {r["Symbol"].strip().upper(): r.get("GICS Sector", "?")
            for r in csv.DictReader(p.open())}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config.yaml")
    ap.add_argument("--quiet", action="store_true", help="suppress the summary print")
    args = ap.parse_args()

    cfg = yaml.safe_load(Path(args.config).read_text())
    store = Store(cfg["data"]["db_path"])
    sc, t, rg, bt = cfg["scoring"], cfg["trade"], cfg["regime"], cfg["backtest"]
    min_bars = cfg["volatility"].get("min_bars") or cfg["volatility"]["atr_period"]
    dp = dict(n=cfg["pivots"]["n_bars"], atr_period=cfg["volatility"]["atr_period"],
              tolerance=cfg["clustering"]["atr_tolerance"],
              min_touches=sc["min_touches"], lookback=cfg["detection"]["lookback_bars"])
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    universe = [l.split("#")[0].strip().upper()
                for l in Path(cfg["universe"]["source_file"]).read_text().splitlines()
                if l.split("#")[0].strip()]
    sectors = load_sectors("data/sp500_constituents.csv")
    frames = {s: store.get_bars(s) for s in universe}
    frames = {s: df for s, df in frames.items() if len(df) >= min_bars}

    # Phase 1: advance existing trades against whatever bars have landed.
    changed = advance_all(store, frames, bt)

    # Phase 2: build today's setups (regime-aware) and record the armed ones.
    index = build_market_index(frames)
    market = regime_series(index, rg["sma_period"]).iloc[-1]
    run_date = index.index[-1].date().isoformat()
    cash_mode = rg["enabled"] and market == "down" and not rg["allow_shorts"]
    short_mode = rg["enabled"] and market == "down" and rg["allow_shorts"]

    recorded = []
    if not cash_mode:
        builder = build_short_setup if short_mode else build_setup
        setups = []
        for sym, df in frames.items():
            res = detect_zones(df, **dp)
            scored = score_zones(res["zones"], res["df"], res["atr"], sc["weights"],
                                 sc["params"], atr_pct=res["atr_pct"])
            closes = res["df"]["close"].to_numpy()
            trend = trend_state(closes, t["trend_sma_period"]) if t.get("require_trend") else None
            setup = builder(sym, scored, float(closes[-1]), res["atr"], t,
                            closes=closes, trend=trend)
            setup["sector"] = sectors.get(sym, "?")
            setups.append(setup)
        recorded = record_setups(store, setups, run_date, now)

    if not args.quiet:
        _report(run_date, market, cash_mode, short_mode, changed, recorded)


def _report(run_date, market, cash_mode, short_mode, changed, recorded):
    fills = [t for t in changed if t["status"] == "OPEN"]
    closes = [t for t in changed if t["status"] in ("CLOSED", "CANCELLED")]
    print(f"PAPER LEDGER  (bars through {run_date} · market {market.upper()})")
    mode = "  CASH MODE — no new longs recorded." if cash_mode else \
           ("  SHORT MODE." if short_mode else "")
    if mode:
        print(mode)
    print(f"  advanced: {len(fills)} filled, {len(closes)} closed · "
          f"recorded: {len(recorded)} new pending")
    for t in closes:
        tag = t["exit_reason"].upper()
        r = t.get("r_multiple")
        rtxt = f"{r:+.2f}R" if r is not None else "  —  "
        print(f"    {t['symbol']:<6} {t['side']:<5} {tag:<8} {rtxt}")
    for t in recorded:
        print(f"    {t['symbol']:<6} {t['side']:<5} NEW-PENDING entry {t['entry']:.2f}")


if __name__ == "__main__":
    main()
