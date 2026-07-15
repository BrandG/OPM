"""Print scored S/R zones for one or more symbols.

Detects zones (trailing window) and ranks them by the 0-100 composite, showing
the per-component breakdown so the weighting can be sanity-checked and tuned.

Usage:
    python scripts/score.py [--symbols KO,AMD,MRVL] [--top 8] [--config config.yaml]
"""

import argparse
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.storage import Store
from src.zones import detect_zones
from src.scoring import score_zones


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config.yaml")
    ap.add_argument("--symbols", default="KO,MRVL,AMD,ORCL,JNJ,SMCI")
    ap.add_argument("--top", type=int, default=8)
    args = ap.parse_args()

    cfg = yaml.safe_load(Path(args.config).read_text())
    store = Store(cfg["data"]["db_path"])
    sc = cfg["scoring"]
    dp = dict(n=cfg["pivots"]["n_bars"], atr_period=cfg["volatility"]["atr_period"],
              tolerance=cfg["clustering"]["atr_tolerance"],
              min_touches=sc["min_touches"], lookback=cfg["detection"]["lookback_bars"])

    for sym in [s.strip().upper() for s in args.symbols.split(",") if s.strip()]:
        df = store.get_bars(sym)
        if df.empty:
            print(f"{sym}: no bars\n")
            continue
        res = detect_zones(df, **dp)
        scored = score_zones(res["zones"], res["df"], res["atr"],
                             sc["weights"], sc["params"], atr_pct=res["atr_pct"])
        last = float(res["df"]["close"].iloc[-1])
        print(f"=== {sym}  (last {last:.2f}, ATR {res['atr']:.2f}, "
              f"{len(scored)} zones) ===")
        print(f"{'score':>5} {'kind':10} {'zone':>20} {'tch':>3}  "
              f"{'tou bou ang psy con rec':>27}")
        for z in scored[: args.top]:
            s = z["subscores"]
            brk = " ".join(f"{s[k]:.2f}" for k in
                           ("touches", "bounce", "angle", "psych", "containment", "recency"))
            zr = f"{z['low']:.2f}-{z['high']:.2f}"
            print(f"{z['score']:>5.1f} {z['kind']:10} {zr:>20} {z['touches']:>3}  {brk}")
        print()


if __name__ == "__main__":
    main()
