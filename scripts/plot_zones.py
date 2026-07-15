"""Phase 3 validation gate: overlay detected S/R zones on real price charts.

For each symbol: run pivots -> clustering, then draw daily high/low bars, the
close line, pivot markers, and shaded zone bands (green=support, red=resistance,
gold=mixed/flip). Band opacity scales with touch count. Look at these BEFORE any
scoring is written — this is where detection bugs hide silently.

Usage:
    python scripts/plot_zones.py [--symbols SMCI,MRVL,AMD,ORCL,KO,JNJ] [--config config.yaml]
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

BG, FG, GRID = "#ffffff", "#1f2933", "#e4e7eb"
C_SUP, C_RES, C_MIX = "#2f9e44", "#e03131", "#f08c00"
DEFAULT = ["SMCI", "MRVL", "AMD", "ORCL", "KO", "JNJ"]


def _kind_color(kind):
    return {"support": C_SUP, "resistance": C_RES, "mixed": C_MIX}[kind]


def plot_symbol(ax, sym, df, res):
    x = np.arange(len(df))
    ax.vlines(x, df["low"].to_numpy(), df["high"].to_numpy(),
              color="#adb5bd", linewidth=0.6, alpha=0.6, zorder=1)
    ax.plot(x, df["close"].to_numpy(), color=FG, linewidth=0.8, alpha=0.75, zorder=2)

    # Pivot markers.
    for p in res["pivots"]:
        ax.scatter(p["idx"], p["price"], s=14, zorder=3,
                   color=C_SUP if p["kind"] == "low" else C_RES,
                   edgecolor="none", alpha=0.8)

    # Zone bands span the full width; opacity grows with the composite score.
    xmax = len(df) - 1
    for z in res["zones"]:
        col = _kind_color(z["kind"])
        ax.axhspan(z["low"], z["high"], color=col,
                   alpha=0.10 + 0.35 * (z["score"] / 100), zorder=0)
        ax.text(xmax * 1.005, z["center"], f"{z['score']:.0f}",
                va="center", ha="left", fontsize=7, color=col, fontweight="bold")

    ax.set_title(f"{sym}   ATR {res['atr']:.2f}   ·   {len(res['zones'])} zones "
                 f"(label = 0-100 score)",
                 fontsize=11, fontweight="bold", color=FG, loc="left")
    ax.set_facecolor(BG)
    ax.grid(axis="y", color=GRID, zorder=0)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    ax.tick_params(colors=FG, labelsize=8)
    ax.set_xticks([])
    ax.set_xlim(0, xmax * 1.03)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config.yaml")
    ap.add_argument("--symbols", default=",".join(DEFAULT))
    ap.add_argument("--out", default="reports/phase3_zones.png")
    args = ap.parse_args()

    cfg = yaml.safe_load(Path(args.config).read_text())
    store = Store(cfg["data"]["db_path"])
    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]

    n = cfg["pivots"]["n_bars"]
    atr_period = cfg["volatility"]["atr_period"]
    tol = cfg["clustering"]["atr_tolerance"]
    lookback = cfg["detection"]["lookback_bars"]
    min_touches = cfg["scoring"]["min_touches"]
    weights = cfg["scoring"]["weights"]
    params = cfg["scoring"]["params"]

    cols = 2
    rows = (len(symbols) + cols - 1) // cols
    fig, axes = plt.subplots(rows, cols, figsize=(cols * 8, rows * 3.6))
    fig.patch.set_facecolor(BG)
    axes = np.atleast_1d(axes).ravel()
    for ax in axes[len(symbols):]:
        ax.set_visible(False)

    for sym, ax in zip(symbols, axes):
        df = store.get_bars(sym)
        if df.empty:
            ax.set_visible(False)
            print(f"{sym}: no bars")
            continue
        res = detect_zones(df, n=n, atr_period=atr_period, tolerance=tol,
                           min_touches=min_touches, lookback=lookback)
        res["zones"] = score_zones(res["zones"], res["df"], res["atr"], weights,
                                   params, atr_pct=res["atr_pct"])
        res["min_touches"] = min_touches
        plot_symbol(ax, sym, res["df"], res)  # window used for detection

        # Text sanity dump — top zones by score.
        print(f"\n{sym}: ATR {res['atr']:.2f}, {len(res['pivots'])} pivots, "
              f"{len(res['zones'])} zones")
        for z in res["zones"][:6]:
            print(f"  {z['score']:>5.1f}  {z['kind']:10s} {z['low']:.2f}-{z['high']:.2f} "
                  f"({z['touches']} touches, width {z['width_atr']:.2f} ATR, "
                  f"last {z['last_touch'].date()})")

    fig.suptitle("Phase 3 — detected S/R zones (green=support · red=resistance · gold=flip)",
                 fontsize=13, fontweight="bold", color=FG, x=0.01, ha="left")
    fig.tight_layout(rect=[0, 0, 1, 0.97])
    Path(args.out).parent.mkdir(exist_ok=True)
    fig.savefig(args.out, dpi=140, facecolor=BG, bbox_inches="tight")
    plt.close(fig)
    print(f"\nWrote {args.out}")


if __name__ == "__main__":
    main()
