"""Full pipeline scan: universe -> zones -> scores -> bracket setups.

Regime-aware: builds a synthetic market index and, if the market is below its
trend and the cash switch is on, suppresses new longs ("cash is a position")
rather than dip-buying into a downturn. Sector-aware: reports how concentrated
the surviving setups are (the AI-capex concentration risk).

Usage:
    python scripts/scan.py [--top 25] [--armed-only] [--config config.yaml]
"""

import argparse
import csv
import sys
from collections import Counter
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.storage import Store
from src.zones import detect_zones
from src.scoring import score_zones
from src.trades import build_setup, build_short_setup
from src.trend import trend_state
from src.regime import build_market_index, regime_series


def load_universe(path: str) -> list[str]:
    out = []
    for line in Path(path).read_text().splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            out.append(line.upper())
    return out


def load_sectors(path: str) -> dict:
    p = Path(path)
    if not p.exists():
        return {}
    return {r["Symbol"].strip().upper(): r.get("GICS Sector", "?")
            for r in csv.DictReader(p.open())}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config.yaml")
    ap.add_argument("--top", type=int, default=25)
    ap.add_argument("--armed-only", action="store_true")
    ap.add_argument("--save", action="store_true",
                    help="write the setups to reports/watchlist_<date>.csv")
    ap.add_argument("--out", default=None, help="override the --save path")
    args = ap.parse_args()

    cfg = yaml.safe_load(Path(args.config).read_text())
    store = Store(cfg["data"]["db_path"])
    sc, t, rg = cfg["scoring"], cfg["trade"], cfg["regime"]
    min_bars = cfg["volatility"].get("min_bars") or cfg["volatility"]["atr_period"]
    dp = dict(n=cfg["pivots"]["n_bars"], atr_period=cfg["volatility"]["atr_period"],
              tolerance=cfg["clustering"]["atr_tolerance"],
              min_touches=sc["min_touches"], lookback=cfg["detection"]["lookback_bars"])

    universe = load_universe(cfg["universe"]["source_file"])
    sectors = load_sectors("data/sp500_constituents.csv")
    frames = {s: store.get_bars(s) for s in universe}
    frames = {s: df for s, df in frames.items() if len(df) >= min_bars}

    # --- market regime (the cash switch) ---
    index = build_market_index(frames)
    market = regime_series(index, rg["sma_period"]).iloc[-1]
    trend_pct = (index.iloc[-1] / index.rolling(rg["sma_period"]).mean().iloc[-1] - 1) * 100
    print(f"MARKET REGIME: {market.upper()}  (index {trend_pct:+.1f}% vs its "
          f"{rg['sma_period']}-day trend)\n")

    cash_mode = rg["enabled"] and market == "down" and not rg["allow_shorts"]
    short_mode = rg["enabled"] and market == "down" and rg["allow_shorts"]
    if cash_mode:
        print("*** CASH MODE: market is below trend -> suppressing new long setups. ***")
        print("    (Existing positions run to their brackets; no new dip-buys into a downturn.)\n")

    setups, scanned, blue_sky, into_res, far_target = [], 0, 0, 0, 0
    for sym, df in frames.items():
        scanned += 1
        res = detect_zones(df, **dp)
        scored = score_zones(res["zones"], res["df"], res["atr"],
                             sc["weights"], sc["params"], atr_pct=res["atr_pct"])
        price = float(res["df"]["close"].iloc[-1])
        closes = res["df"]["close"].to_numpy()
        trend = trend_state(closes, t["trend_sma_period"]) if t.get("require_trend") else None
        builder = build_short_setup if short_mode else build_setup
        setup = builder(sym, scored, price, res["atr"], t, closes=closes, trend=trend)
        if setup["reasons"] == ["no_resistance_above"]:
            blue_sky += 1
        if setup["reasons"] == ["approaching_from_below"]:
            into_res += 1
        if "target_unreachable" in setup["reasons"]:
            far_target += 1
        if setup["passed"] and not cash_mode:
            setup["sector"] = sectors.get(sym, "?")
            setups.append(setup)

    setups.sort(key=lambda s: (s["armed"], s["trade_score"]), reverse=True)
    if args.armed_only:
        setups = [s for s in setups if s["armed"]]

    side = "SHORT" if short_mode else "LONG"
    far_txt = f" · {far_target} far-target skipped" if t.get("max_target_atr") else ""
    print(f"Scanned {scanned} symbols · {len(setups)} {side} passed gates · "
          f"{blue_sky} blue-sky · {into_res} rising-into-resistance skipped{far_txt}\n")

    if not cash_mode:
        hdr = (f"{'sym':<6}{'A':<2}{'price':>8}{'entry':>8}{'stop':>8}{'target':>8}"
               f"{'rr':>5}{'corr':>6}{'tATR':>6}{'tscr':>6}  sector")
        print(hdr); print("-" * (len(hdr) + 8))
        for s in setups[: args.top]:
            # tATR = target distance in ATRs. A big value means the R/R is inflated by
            # a far level the ~2-week hold won't reach -> flag it so it isn't overweighted.
            far = " far" if s.get("target_dist_atr", 0) > 12 else ""
            print(f"{s['symbol']:<6}{'*' if s['armed'] else ' ':<2}"
                  f"{s['price']:>8.2f}{s['entry']:>8.2f}{s['stop']:>8.2f}{s['target']:>8.2f}"
                  f"{s['rr']:>5.1f}{s['corridor_pct']*100:>5.1f}%{s.get('target_dist_atr',0):>6.1f}"
                  f"{s['trade_score']:>6.1f}  {s.get('sector','?')}{far}")

        # --- sector concentration (the AI-capex exposure check) ---
        if setups:
            armed = [s for s in setups if s["armed"]]
            pool = armed or setups
            counts = Counter(s.get("sector", "?") for s in pool)
            total = sum(counts.values())
            print(f"\nSector mix of {'armed' if armed else 'passed'} setups ({total}):")
            for sec, c in counts.most_common():
                bar = "#" * round(20 * c / total)
                print(f"  {sec:<24}{c:>3} {c/total:>5.0%} {bar}")
            tech = counts.get("Information Technology", 0)
            if total and tech / total >= 0.30:
                print(f"  ! {tech/total:.0%} in Information Technology — heavy AI-capex "
                      f"concentration; size accordingly.")

    # --- optional CSV export ---
    if args.save and not cash_mode:
        as_of = index.index[-1].date().isoformat()
        out = Path(args.out) if args.out else Path(f"reports/watchlist_{as_of}.csv")
        out.parent.mkdir(exist_ok=True)
        cols = ["symbol", "side", "sector", "armed", "price", "entry", "stop", "target",
                "rr", "target_dist_atr", "risk_pct", "reward_pct", "corridor_pct",
                "trade_score"]
        with out.open("w", newline="") as f:
            w = csv.writer(f)
            w.writerow(cols)
            for s in setups:
                w.writerow([s["symbol"], s.get("side", "long"), s.get("sector", "?"),
                            int(s["armed"]), s["price"], s["entry"], s["stop"], s["target"],
                            s["rr"], s.get("target_dist_atr", 0), s["risk_pct"],
                            s["reward_pct"], s["corridor_pct"], s["trade_score"]])
        print(f"\nSaved {len(setups)} setups (as of {as_of} close) -> {out}")


if __name__ == "__main__":
    main()
