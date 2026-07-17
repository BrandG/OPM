"""The recurring runner: scan, diff against last run, emit only what CHANGED.

Designed to run on a schedule (daily post-close is the natural cadence given no
intraday access: "here's what's newly armed, place GTC brackets before the open";
a 30-min intraday loop just needs a live-quote refresh wired in — see NOTE below).

Each run:
  1. classify the market regime (and alert if it flipped),
  2. build setups across the universe (respecting the cash switch),
  3. diff each symbol against its stored state and record only transitions,
  4. append the alert digest to reports/alerts.log and print it.

Usage:
    python scripts/monitor.py [--config config.yaml] [--quiet-if-empty]
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
from src.alerts import evaluate, format_event, ACTIONABLE
from src.notify_email import build_digest_html, send_report

# NOTE: setups are computed from the cached daily bars. For a true intraday
# 30-min loop, refresh survivors' last price here (yfinance delayed quote or IBKR
# live) before build_setup so `armed` reflects the current intraday price.


def load_sectors(path: str) -> dict:
    p = Path(path)
    if not p.exists():
        return {}
    return {r["Symbol"].strip().upper(): r.get("GICS Sector", "?")
            for r in csv.DictReader(p.open())}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config.yaml")
    ap.add_argument("--quiet-if-empty", action="store_true",
                    help="print nothing when there are no changes")
    args = ap.parse_args()

    cfg = yaml.safe_load(Path(args.config).read_text())
    store = Store(cfg["data"]["db_path"])
    sc, t, rg = cfg["scoring"], cfg["trade"], cfg["regime"]
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

    index = build_market_index(frames)
    market = regime_series(index, rg["sma_period"]).iloc[-1]
    cash_mode = rg["enabled"] and market == "down" and not rg["allow_shorts"]
    short_mode = rg["enabled"] and market == "down" and rg["allow_shorts"]

    events = []
    prev_reg = store.get_meta("last_regime")
    if prev_reg and prev_reg != market:
        events.append({"symbol": "—", "event": "REGIME",
                       "from_state": prev_reg, "to_state": market})
    store.set_meta("last_regime", market)

    if cash_mode:
        for st in store.all_setup_states():          # market rolled over -> clear longs
            ev, _ = evaluate(st["symbol"], st, None, now)
            events += ev
            store.clear_setup_state(st["symbol"])
    else:
        builder = build_short_setup if short_mode else build_setup
        for sym, df in frames.items():
            res = detect_zones(df, **dp)
            scored = score_zones(res["zones"], res["df"], res["atr"],
                                 sc["weights"], sc["params"], atr_pct=res["atr_pct"])
            closes = res["df"]["close"].to_numpy()
            trend = trend_state(closes, t["trend_sma_period"]) if t.get("require_trend") else None
            setup = builder(sym, scored, float(closes[-1]), res["atr"], t,
                            closes=closes, trend=trend)
            setup["sector"] = sectors.get(sym, "?")
            prev = store.get_setup_state(sym)
            ev, rec = evaluate(sym, prev, setup, now)
            events += ev
            if rec:
                store.set_setup_state(rec)
            elif prev:
                store.clear_setup_state(sym)

    _report(now, market, index, rg, cash_mode, short_mode, events, args.quiet_if_empty)
    _maybe_email(cfg, now, market, events)


def _maybe_email(cfg, now, market, events):
    """Email the actionable digest (change-only) — only when something armed or
    cleared. Never raises; a send failure is logged, not fatal."""
    armed = [e for e in events if e["event"] == "ARMED"]
    cleared = [e for e in events if e["event"] == "CLEARED"]
    if not (armed or cleared):
        return
    header = f"{now} · market {market.upper()} · place ARMED as GTC brackets before the open"
    subject = f"OPM: {len(armed)} armed, {len(cleared)} cleared ({market.upper()})"
    html = build_digest_html(armed, cleared, header)
    reason = send_report(cfg, subject, html)
    if reason:
        print(f"  [email] not sent: {reason}")


def _report(now, market, index, rg, cash_mode, short_mode, events, quiet):
    order = {"REGIME": 0, "ARMED": 1, "CLEARED": 2, "NEW_WATCH": 3, "DISARMED": 4}
    events.sort(key=lambda e: order.get(e["event"], 9))
    actionable = [e for e in events if e["event"] in ACTIONABLE]

    if quiet and not events:
        return

    trend_pct = (index.iloc[-1] / index.rolling(rg["sma_period"]).mean().iloc[-1] - 1) * 100
    lines = [f"[{now}]  MARKET {market.upper()} ({trend_pct:+.1f}% vs {rg['sma_period']}d trend)"
             f"  ·  {len(actionable)} action / {len(events)} changes"]
    if cash_mode:
        lines.append("  CASH MODE — market below trend; new longs suppressed.")
    if short_mode:
        lines.append("  SHORT MODE — market below trend; emitting shorts.")
    for e in events:
        if e["event"] == "REGIME":
            lines.append(f"  ** REGIME CHANGE: {e['from_state'].upper()} -> "
                         f"{e['to_state'].upper()} **")
        else:
            lines.append(format_event(e))
    if not events:
        lines.append("  (no changes since last run)")

    text = "\n".join(lines)
    print(text)
    log = Path("reports/alerts.log")
    log.parent.mkdir(exist_ok=True)
    with log.open("a") as f:
        f.write(text + "\n\n")


if __name__ == "__main__":
    main()
