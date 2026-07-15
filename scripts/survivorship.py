"""Quantify survivorship-bias exposure without leaving our trusted data.

Names get removed from the S&P 500 after sustained declines; our strategy buys
dips. So we bucket every symbol by its total return over the window and measure
the strategy's R-expectancy in each bucket. If the edge lives only in the
up-trending buckets, then the *missing* (removed, down-trending) names would drag
the true edge down — and we can estimate by how much.

Usage:
    python scripts/survivorship.py [--config config.yaml]
"""

import sys
from pathlib import Path
from statistics import mean

import numpy as np
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.storage import Store
from src.backtest import simulate_symbol, summarize


def main() -> None:
    cfg = yaml.safe_load(Path("config.yaml").read_text())
    store = Store(cfg["data"]["db_path"])
    sc, t, bt = cfg["scoring"], cfg["trade"], cfg["backtest"]
    min_bars = bt["warmup_bars"] + 5
    dp = dict(n=cfg["pivots"]["n_bars"], atr_period=cfg["volatility"]["atr_period"],
              tolerance=cfg["clustering"]["atr_tolerance"],
              min_touches=sc["min_touches"], lookback=cfg["detection"]["lookback_bars"])

    universe = [l.split("#")[0].strip().upper()
                for l in Path(cfg["universe"]["source_file"]).read_text().splitlines()
                if l.split("#")[0].strip()]

    rows = []  # (sym, ret_2y, trades)
    for sym in universe:
        df = store.get_bars(sym)
        if len(df) < min_bars:
            continue
        df.index.name = sym
        ret = float(df["close"].iloc[-1] / df["close"].iloc[0] - 1)
        trades = simulate_symbol(df, dp, t, bt, sc["weights"], sc["params"])
        rows.append((sym, ret, trades))

    rows.sort(key=lambda r: r[1])                      # ascending by return
    n = len(rows)
    print(f"{n} symbols with full history.\n")

    # --- expectancy by return quintile ---
    print("Strategy edge by the stock's total return over the window:")
    hdr = f"{'bucket':<22}{'syms':>5}{'trades':>8}{'win%':>7}{'exp_R':>8}{'PF':>6}{'totR':>7}"
    print(hdr); print("-" * len(hdr))
    q = 5
    for b in range(q):
        chunk = rows[b * n // q:(b + 1) * n // q]
        lo, hi = chunk[0][1], chunk[-1][1]
        trades = [tr for _, _, ts in chunk for tr in ts]
        s = summarize(trades)
        label = f"{lo*100:+.0f}%..{hi*100:+.0f}%"
        if not s["n_trades"]:
            print(f"{label:<22}{len(chunk):>5}{0:>8}   (no trades)")
            continue
        print(f"{label:<22}{len(chunk):>5}{s['n_trades']:>8}{s['win_rate']*100:>6.1f}%"
              f"{s['expectancy_r']:>+8.3f}{s['profit_factor']:>6.2f}{s['total_r']:>+7.0f}")

    # --- down-movers vs up-movers (the survivorship-relevant split) ---
    down = [tr for _, r, ts in rows if r < 0 for tr in ts]
    up = [tr for _, r, ts in rows if r >= 0 for tr in ts]
    ds, us = summarize(down), summarize(up)
    print(f"\nDOWN over window (<0%):  {len([r for r in rows if r[1] < 0]):>3} syms  "
          f"{ds.get('n_trades',0):>4} trades  exp {ds.get('expectancy_r',0):+.3f}R  "
          f"PF {ds.get('profit_factor',0)}")
    print(f"UP   over window (>=0%): {len([r for r in rows if r[1] >= 0]):>3} syms  "
          f"{us.get('n_trades',0):>4} trades  exp {us.get('expectancy_r',0):+.3f}R  "
          f"PF {us.get('profit_factor',0)}")

    # --- correlation: does a stock's own edge track its trend? ---
    per = [(r, summarize(ts)["expectancy_r"]) for _, r, ts in rows if ts]
    if len(per) > 2:
        rr = np.array([p[0] for p in per]); ee = np.array([p[1] for p in per])
        corr = float(np.corrcoef(rr, ee)[0, 1])
        print(f"\ncorr(stock 2y return, its expectancy_R) = {corr:+.2f}  "
              f"(positive => edge concentrated in winners => survivorship inflates)")


if __name__ == "__main__":
    main()
