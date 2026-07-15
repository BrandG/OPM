"""Does trade_score predict realized edge? Bucket backtest trades by score.

Settles the concentration-vs-diversification question: if higher-score setups earn
materially higher expectancy, taking fewer/better ones has a quality argument; if
the curve is flat, score doesn't rank edge and diversification wins outright.

Usage:
    python scripts/edge_by_score.py [--config config.yaml] [--buckets 5]
"""

import argparse
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.storage import Store
from src.backtest import simulate_symbol, summarize


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config.yaml")
    ap.add_argument("--buckets", type=int, default=5, help="quantile buckets (5=quintiles)")
    args = ap.parse_args()

    cfg = yaml.safe_load(Path(args.config).read_text())
    store = Store(cfg["data"]["db_path"])
    sc, t, bt = cfg["scoring"], cfg["trade"], cfg["backtest"]
    dp = dict(n=cfg["pivots"]["n_bars"], atr_period=cfg["volatility"]["atr_period"],
              tolerance=cfg["clustering"]["atr_tolerance"],
              min_touches=sc["min_touches"], lookback=cfg["detection"]["lookback_bars"])

    universe = [l.split("#")[0].strip().upper()
                for l in Path(cfg["universe"]["source_file"]).read_text().splitlines()
                if l.split("#")[0].strip()]

    trades = []
    for s in universe:
        df = store.get_bars(s)
        if len(df) < cfg["volatility"]["min_bars"]:
            continue
        df.index.name = s
        trades.extend(simulate_symbol(df, dp, t, bt, sc["weights"], sc["params"]))

    trades = [x for x in trades if x.get("trade_score") is not None]
    if not trades:
        print("no trades"); return
    trades.sort(key=lambda x: x["trade_score"])
    n = len(trades)
    b = args.buckets

    print(f"{n} trades · edge by trade_score ({b}-quantile buckets, low→high)\n")
    hdr = f"{'score range':>14}{'n':>6}{'exp_R':>8}{'PF':>6}{'win%':>7}{'totR':>7}"
    print(hdr); print("-" * len(hdr))
    for k in range(b):
        chunk = trades[k * n // b:(k + 1) * n // b]
        st = summarize(chunk)
        lo, hi = chunk[0]["trade_score"], chunk[-1]["trade_score"]
        print(f"{lo:>6.0f}–{hi:<6.0f}{st['n_trades']:>6}{st['expectancy_r']:>+8.3f}"
              f"{st['profit_factor']:>6.2f}{st['win_rate']*100:>6.1f}%{st['total_r']:>+7.0f}")

    # Correlation-ish read: top-bucket vs bottom-bucket expectancy gap.
    top = summarize(trades[(b - 1) * n // b:])
    bot = summarize(trades[: n // b])
    print(f"\ntop bucket {top['expectancy_r']:+.3f}R vs bottom {bot['expectancy_r']:+.3f}R  "
          f"(gap {top['expectancy_r'] - bot['expectancy_r']:+.3f}R)")


if __name__ == "__main__":
    main()
