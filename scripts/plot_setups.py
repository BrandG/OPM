"""Visual check of Phase 5 bracket setups.

Runs the scan, then draws the top armed setups: price with the support and
resistance zones shaded, and entry / stop / target as horizontal lines. Confirm
by eye that entry sits just above support, stop just below it, and target just
below resistance.

Usage:
    python scripts/plot_setups.py [--top 6] [--config config.yaml]
"""

import argparse
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.storage import Store
from src.zones import detect_zones
from src.scoring import score_zones
from src.trades import build_setup

BG, INK, MUTED, GRID = "#fcfcfb", "#0b0b0b", "#898781", "#e1e0d9"
C_SUP, C_RES = "#2f9e44", "#e03131"
C_ENTRY, C_STOP, C_TGT = "#2a78d6", "#c92a2a", "#2b8a3e"


def _detect(store, sym, dp, sc):
    df = store.get_bars(sym)
    res = detect_zones(df, **dp)
    res["zones"] = score_zones(res["zones"], res["df"], res["atr"],
                               sc["weights"], sc["params"], atr_pct=res["atr_pct"])
    return res


def panel(ax, s, res):
    df = res["df"]
    x = np.arange(len(df))
    ax.vlines(x, df["low"], df["high"], color="#adb5bd", lw=0.6, alpha=0.6, zorder=1)
    ax.plot(x, df["close"], color=INK, lw=0.8, alpha=0.75, zorder=2)

    sup, res_z = s["support"], s["resistance"]
    ax.axhspan(sup["low"], sup["high"], color=C_SUP, alpha=0.18, zorder=0)
    ax.axhspan(res_z["low"], res_z["high"], color=C_RES, alpha=0.18, zorder=0)

    xr = len(df) - 1
    for y, c, lab in [(s["entry"], C_ENTRY, "entry"), (s["stop"], C_STOP, "stop"),
                      (s["target"], C_TGT, "target")]:
        ax.axhline(y, color=c, lw=1.4, ls="--", zorder=3)
        ax.text(xr * 1.005, y, f"{lab} {y:.2f}", va="center", ha="left",
                fontsize=8, color=c, fontweight="bold")

    ax.set_title(f"{s['symbol']}   R/R {s['rr']:.1f}  ·  corridor {s['corridor_pct']*100:.1f}%"
                 f"  ·  {s['shares']:.2f} sh  ${s['position_value']:.0f}",
                 fontsize=11, fontweight="bold", color=INK, loc="left")
    ax.set_facecolor(BG)
    ax.grid(axis="y", color=GRID, zorder=0)
    for sp in ("top", "right"):
        ax.spines[sp].set_visible(False)
    ax.tick_params(colors=MUTED, labelsize=8)
    ax.set_xticks([])
    ax.set_xlim(0, xr * 1.06)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config.yaml")
    ap.add_argument("--top", type=int, default=6)
    ap.add_argument("--out", default="reports/phase5_setups.png")
    args = ap.parse_args()

    cfg = yaml.safe_load(Path(args.config).read_text())
    store = Store(cfg["data"]["db_path"])
    sc, t = cfg["scoring"], cfg["trade"]
    min_bars = cfg["volatility"].get("min_bars") or cfg["volatility"]["atr_period"]
    dp = dict(n=cfg["pivots"]["n_bars"], atr_period=cfg["volatility"]["atr_period"],
              tolerance=cfg["clustering"]["atr_tolerance"],
              min_touches=sc["min_touches"], lookback=cfg["detection"]["lookback_bars"])

    universe = [l.split("#")[0].strip().upper()
                for l in Path(cfg["universe"]["source_file"]).read_text().splitlines()
                if l.split("#")[0].strip()]

    setups = []
    for sym in universe:
        if store.bar_count(sym) < min_bars:
            continue
        res = _detect(store, sym, dp, sc)
        s = build_setup(sym, res["zones"], float(res["df"]["close"].iloc[-1]), res["atr"], t,
                        closes=res["df"]["close"].to_numpy())
        if s["passed"] and s["armed"]:
            setups.append((s, res))
    setups.sort(key=lambda sr: sr[0]["trade_score"], reverse=True)
    setups = setups[: args.top]

    cols = 2
    rows = (len(setups) + cols - 1) // cols
    fig, axes = plt.subplots(rows, cols, figsize=(cols * 8, rows * 3.4))
    fig.patch.set_facecolor(BG)
    axes = np.atleast_1d(axes).ravel()
    for ax in axes[len(setups):]:
        ax.set_visible(False)
    for (s, res), ax in zip(setups, axes):
        panel(ax, s, res)

    fig.suptitle("Phase 5 — top armed bracket setups  "
                 "(green=support · red=resistance · dashed=entry/stop/target)",
                 fontsize=13, fontweight="bold", color=INK, x=0.01, ha="left")
    fig.tight_layout(rect=[0, 0, 1, 0.96])
    Path(args.out).parent.mkdir(exist_ok=True)
    fig.savefig(args.out, dpi=140, facecolor=BG, bbox_inches="tight")
    plt.close(fig)
    print(f"Wrote {args.out} ({len(setups)} setups)")


if __name__ == "__main__":
    main()
