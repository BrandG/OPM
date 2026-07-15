"""Out-of-sample robustness check.

Two questions:
  1. STABILITY — is the edge consistent across time sub-periods, or driven by one
     lucky stretch? (full universe, default params, one run)
  2. OVERFITTING — does the one parameter we tuned (stop_atr_buffer) survive a
     train/test split? Pick the best buffer on the FIRST half, then report its
     SECOND-half (out-of-sample) result vs the default and vs the best-on-test
     (the cheat). A large train->test drop = overfitting.

Caveat printed at run time: detection needs a 252-bar warmup, so signals only
occur in roughly the last year of the 2-year cache — the "halves" are ~6-month
sub-periods, not two full years. Small samples; read directionally.
"""

import sys
import time
from collections import defaultdict
from pathlib import Path
from statistics import mean

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.storage import Store
from src.backtest import simulate_symbol, summarize


def run_all(store, universe, dp, t, sc, bt, side="long"):
    trades = []
    for sym in universe:
        df = store.get_bars(sym)
        df.index.name = sym
        trades.extend(simulate_symbol(df, dp, t, bt, sc["weights"], sc["params"], side))
    return trades


def quarter(iso: str) -> str:
    y, m = int(iso[:4]), int(iso[5:7])
    return f"{y}-Q{(m - 1) // 3 + 1}"


def _line(label, s):
    if not s["n_trades"]:
        return f"  {label:<16} (no trades)"
    return (f"  {label:<16} n {s['n_trades']:>4} · win {s['win_rate']:>5.1%} · "
            f"exp {s['expectancy_r']:>+.3f}R · PF {s['profit_factor']:>4}")


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
    universe = [s for s in universe if store.bar_count(s) >= min_bars]

    # ---- Part 1: stability (full universe, default params) ----
    t0 = time.time()
    trades = run_all(store, universe, dp, t, sc, bt)
    sdates = sorted(tr["signal_date"] for tr in trades)
    mid = sdates[len(sdates) // 2]
    print(f"Full run: {len(trades)} trades, signals {sdates[0]}..{sdates[-1]} "
          f"({time.time()-t0:.0f}s)\n")
    print("STABILITY by quarter (default params):")
    byq = defaultdict(list)
    for tr in trades:
        byq[quarter(tr["signal_date"])].append(tr)
    for q in sorted(byq):
        print(_line(q, summarize(byq[q])))

    first = [tr for tr in trades if tr["signal_date"] < mid]
    second = [tr for tr in trades if tr["signal_date"] >= mid]
    print(f"\nSplit at {mid} (equal trade counts):")
    print(_line("first half", summarize(first)))
    print(_line("second half", summarize(second)))

    # ---- Part 2: train/test on stop_atr_buffer (subset for speed) ----
    subset = universe[:150]
    grid = [0.35, 0.5, 0.75, 1.0]
    print(f"\nOVERFITTING test — tune stop_atr_buffer on TRAIN (<{mid}), "
          f"report OOS on TEST (>= {mid})  [{len(subset)} symbols]:")
    print(f"  {'buffer':>7}{'train_exp':>11}{'test_exp':>10}{'test_n':>8}")
    results = []
    for buf in grid:
        t2 = dict(t); t2["stop_atr_buffer"] = buf
        trs = run_all(store, subset, dp, t2, sc, bt)
        tr_train = [x for x in trs if x["signal_date"] < mid]
        tr_test = [x for x in trs if x["signal_date"] >= mid]
        st_tr, st_te = summarize(tr_train), summarize(tr_test)
        results.append((buf, st_tr, st_te))
        print(f"  {buf:>7}{st_tr.get('expectancy_r',0):>+11.3f}"
              f"{st_te.get('expectancy_r',0):>+10.3f}{st_te.get('n_trades',0):>8}")

    best_train = max(results, key=lambda r: r[1].get("expectancy_r", -9))
    best_test = max(results, key=lambda r: r[2].get("expectancy_r", -9))
    default = next(r for r in results if r[0] == 0.35)
    print(f"\n  best-on-TRAIN buffer = {best_train[0]} -> its OOS test exp "
          f"{best_train[2].get('expectancy_r',0):+.3f}R")
    print(f"  default buffer   = 0.35 -> its OOS test exp "
          f"{default[2].get('expectancy_r',0):+.3f}R")
    print(f"  best-on-TEST buffer = {best_test[0]} (the cheat) -> "
          f"{best_test[2].get('expectancy_r',0):+.3f}R")
    print("\nRead: if best-on-train's OOS ~ default's OOS ~ positive, tuning didn't "
          "overfit and the edge holds out-of-sample. If OOS collapses vs train, it did.")


if __name__ == "__main__":
    main()
