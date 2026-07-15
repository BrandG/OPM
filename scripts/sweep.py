"""Sweep one config parameter through values and backtest each — the tuning tool.

Runs on a symbol subset for speed (the ranking of values is what matters; confirm
the winner on the full universe with scripts/backtest.py afterwards).

Usage:
    python scripts/sweep.py --param trade.stop_atr_buffer --values 0.35,0.5,0.75,1.0,1.5 --limit 120
"""

import argparse
import sys
import time
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.storage import Store
from src.backtest import simulate_symbol, summarize


def set_param(cfg: dict, path: str, value):
    section, key = path.split(".", 1)
    cur = cfg[section]
    # support one level of nesting (e.g. scoring.params.touch_cap not needed here)
    cur[key] = value


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config.yaml")
    ap.add_argument("--param", required=True, help="e.g. trade.stop_atr_buffer")
    ap.add_argument("--values", required=True, help="comma list, e.g. 0.35,0.5,0.75")
    ap.add_argument("--limit", type=int, default=120)
    args = ap.parse_args()

    base = yaml.safe_load(Path(args.config).read_text())
    store = Store(base["data"]["db_path"])
    universe = []
    for line in Path(base["universe"]["source_file"]).read_text().splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            universe.append(line.upper())
    universe = universe[: args.limit]
    frames = {s: store.get_bars(s) for s in universe}
    for s, df in frames.items():
        df.index.name = s

    def _parse(v):
        return None if v.strip().lower() in ("null", "none", "off") else float(v)
    values = [_parse(v) for v in args.values.split(",")]
    print(f"Sweeping {args.param} over {values}  ({len(universe)} symbols)\n")
    hdr = f"{'value':>7}{'trades':>8}{'win%':>7}{'exp_R':>8}{'PF':>6}{'stop%':>7}{'recov%':>8}{'totR':>7}"
    print(hdr); print("-" * len(hdr))

    for v in values:
        vlabel = "off" if v is None else f"{v:g}"
        cfg = yaml.safe_load(Path(args.config).read_text())
        set_param(cfg, args.param, v)
        sc, t, bt = cfg["scoring"], cfg["trade"], cfg["backtest"]
        dp = dict(n=cfg["pivots"]["n_bars"], atr_period=cfg["volatility"]["atr_period"],
                  tolerance=cfg["clustering"]["atr_tolerance"],
                  min_touches=sc["min_touches"], lookback=cfg["detection"]["lookback_bars"])
        t0 = time.time()
        trades = []
        for s in universe:
            trades.extend(simulate_symbol(frames[s], dp, t, bt, sc["weights"], sc["params"]))
        st = summarize(trades)
        if not st["n_trades"]:
            print(f"{vlabel:>7}{'0':>8}  (no trades)")
            continue
        print(f"{vlabel:>7}{st['n_trades']:>8}{st['win_rate']*100:>6.1f}%"
              f"{st['expectancy_r']:>+8.3f}{st['profit_factor']:>6.2f}"
              f"{st['pct_stop']*100:>6.0f}%{st['stopped_then_recovered']*100:>7.0f}%"
              f"{st['total_r']:>+7.0f}   ({time.time()-t0:.0f}s)")


if __name__ == "__main__":
    main()
