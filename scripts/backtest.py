"""Run the walk-forward backtest over the universe and report edge.

Usage:
    python scripts/backtest.py [--limit N] [--symbols A,B] [--config config.yaml]
                               [--by-symbol]
"""

import argparse
import sys
import time
from collections import defaultdict
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.storage import Store
from src.backtest import simulate_symbol, summarize


def _print_summary(label, s):
    if not s["n_trades"]:
        print(f"{label}: no trades")
        return
    print(f"{label:<10} trades {s['n_trades']:>5} · win {s['win_rate']:>5.1%} · "
          f"exp {s['expectancy_r']:>+.3f}R · PF {s['profit_factor']:>4} · "
          f"totR {s['total_r']:>+6.0f} · tgt/stop {s['pct_target']:.0%}/{s['pct_stop']:.0%}")


def _monthly_r(trades):
    m = defaultdict(float)
    for t in trades:
        m[t["signal_date"][:7]] += t["r_multiple"]
    return m


def _corr(a: dict, b: dict) -> float:
    keys = sorted(set(a) | set(b))
    if len(keys) < 3:
        return float("nan")
    xs = [a.get(k, 0.0) for k in keys]
    ys = [b.get(k, 0.0) for k in keys]
    n = len(keys)
    mx, my = sum(xs) / n, sum(ys) / n
    cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    vx = sum((x - mx) ** 2 for x in xs) ** 0.5
    vy = sum((y - my) ** 2 for y in ys) ** 0.5
    return cov / (vx * vy) if vx and vy else float("nan")


def load_universe(path: str) -> list[str]:
    out = []
    for line in Path(path).read_text().splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            out.append(line.upper())
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config.yaml")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--symbols", default=None)
    ap.add_argument("--by-symbol", action="store_true")
    ap.add_argument("--side", choices=["long", "short", "both"], default="long")
    ap.add_argument("--require-trend", action="store_true",
                    help="gate longs to uptrends / shorts to downtrends")
    args = ap.parse_args()

    cfg = yaml.safe_load(Path(args.config).read_text())
    store = Store(cfg["data"]["db_path"])
    sc, t, bt = cfg["scoring"], cfg["trade"], cfg["backtest"]
    if args.require_trend:
        t["require_trend"] = True
    dp = dict(n=cfg["pivots"]["n_bars"], atr_period=cfg["volatility"]["atr_period"],
              tolerance=cfg["clustering"]["atr_tolerance"],
              min_touches=sc["min_touches"], lookback=cfg["detection"]["lookback_bars"])

    if args.symbols:
        universe = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    else:
        universe = load_universe(cfg["universe"]["source_file"])
        if args.limit:
            universe = universe[: args.limit]

    sides = ["long", "short"] if args.side == "both" else [args.side]
    trades_by_side = {s: [] for s in sides}
    t0 = time.time()
    for k, sym in enumerate(universe, 1):
        df = store.get_bars(sym)
        df.index.name = sym                              # so build_setup labels it
        for sd in sides:
            trs = simulate_symbol(df, dp, t, bt, sc["weights"], sc["params"], side=sd)
            for tr in trs:
                tr["symbol"] = sym
            trades_by_side[sd].extend(trs)
        if k % 100 == 0:
            tot = sum(len(v) for v in trades_by_side.values())
            print(f"  ...{k}/{len(universe)} symbols, {tot} trades ({time.time()-t0:.0f}s)")

    print(f"\n=== Backtest over {len(universe)} symbols · {time.time()-t0:.0f}s ===")
    for sd in sides:
        _print_summary(sd, summarize(trades_by_side[sd]))

    if args.side == "both":
        combined = trades_by_side["long"] + trades_by_side["short"]
        _print_summary("combined", summarize(combined))
        c = _corr(_monthly_r(trades_by_side["long"]), _monthly_r(trades_by_side["short"]))
        print(f"\nmonthly-R correlation, long vs short: {c:+.2f}  "
              f"(negative => the two sides hedge; near 0 => independent)")

    if args.by_symbol and len(sides) == 1:
        by = {}
        for tr in trades_by_side[sides[0]]:
            by.setdefault(tr["symbol"], []).append(tr)
        ranked = sorted(((s, summarize(v)) for s, v in by.items()),
                        key=lambda x: x[1]["total_r"], reverse=True)
        print("\nTop/bottom symbols by total R:")
        for sym, st in ranked[:8] + ranked[-8:]:
            print(f"  {sym:<6} {st['n_trades']:>3} trades  "
                  f"{st['expectancy_r']:+.2f}R/trade  total {st['total_r']:+.0f}R")


if __name__ == "__main__":
    main()
