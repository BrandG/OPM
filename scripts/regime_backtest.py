"""Regime-conditioned backtest: long & short expectancy in up vs down markets.

Answers "does the short side flip when the market falls?" empirically: build a
synthetic market index, tag every trade by the market regime at its signal date,
and report each side's edge in market-up vs market-down periods.

Usage:
    python scripts/regime_backtest.py [--config config.yaml]
"""

import sys
import time
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.storage import Store
from src.backtest import simulate_symbol, summarize
from src.regime import build_market_index, regime_by_date, regime_series


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
    frames = {s: store.get_bars(s) for s in universe}
    frames = {s: df for s, df in frames.items() if len(df)}

    index = build_market_index(frames)
    reg_map = regime_by_date(index, period=200)
    reg_ser = regime_series(index, period=200)

    # Characterise the sample so nobody over-reads a mild-pullback regime.
    classified = reg_ser[reg_ser.index >= index.index[200]]
    down_frac = (classified == "down").mean()
    peak = index.cummax()
    max_dd = float((index / peak - 1).min())
    print(f"Synthetic index over {len(index)} days: "
          f"{down_frac:.0%} of classified days were 'market-down', "
          f"worst drawdown {max_dd:.1%}.")
    print("(Reminder: this window is a bull market with mild pullbacks — no real "
          "crash. Direction is meaningful; crash magnitude is NOT in the data.)\n")

    buckets = {("long", "up"): [], ("long", "down"): [],
               ("short", "up"): [], ("short", "down"): []}
    t0 = time.time()
    for k, (sym, df) in enumerate(frames.items(), 1):
        df.index.name = sym
        for side in ("long", "short"):
            for tr in simulate_symbol(df, dp, t, bt, sc["weights"], sc["params"], side=side):
                mkt = reg_map.get(tr["signal_date"], "up")
                buckets[(side, mkt)].append(tr)
        if k % 100 == 0:
            print(f"  ...{k}/{len(frames)} ({time.time()-t0:.0f}s)")

    print(f"\n=== Long & short edge by market regime ({time.time()-t0:.0f}s) ===")
    hdr = f"{'side':<6}{'market':<7}{'trades':>7}{'win%':>7}{'exp_R':>8}{'PF':>6}{'totR':>8}"
    print(hdr); print("-" * len(hdr))
    for side in ("long", "short"):
        for mkt in ("up", "down"):
            s = summarize(buckets[(side, mkt)])
            if not s["n_trades"]:
                print(f"{side:<6}{mkt:<7}{'0':>7}   (no trades)")
                continue
            print(f"{side:<6}{mkt:<7}{s['n_trades']:>7}{s['win_rate']*100:>6.1f}%"
                  f"{s['expectancy_r']:>+8.3f}{s['profit_factor']:>6.2f}{s['total_r']:>+8.0f}")
    print("\nRead: if short/down is materially better than short/up, the short "
          "side does flip with the regime.")


if __name__ == "__main__":
    main()
