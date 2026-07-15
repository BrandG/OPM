"""Decompose zone scores into their six weighted component contributions.

Each zone is a horizontal stacked bar whose segments are (weight x sub-score)
for touches / bounce / angle / psych / containment / recency. Segment lengths
sum to the 0-100 composite, so you can read WHICH factors drive each zone and
how the mix differs between zones and between stocks.

Usage:
    python scripts/plot_scores.py [--symbols KO,MRVL,AMD] [--top 8] [--config config.yaml]
"""

import argparse
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Patch
import numpy as np
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.storage import Store
from src.zones import detect_zones
from src.scoring import score_zones

# Component order + reference-palette categorical slots 1-6 (light mode).
COMPONENTS = [
    ("touches", "#2a78d6"),
    ("bounce", "#1baf7a"),
    ("angle", "#eda100"),
    ("psych", "#008300"),
    ("containment", "#4a3aa7"),
    ("recency", "#e34948"),
]
SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK2 = "#52514e"
MUTED = "#898781"
GRID = "#e1e0d9"
KIND_ABBR = {"support": "S", "resistance": "R", "mixed": "F"}


def panel(ax, sym, scored, weights, top):
    zones = scored[:top]
    y = np.arange(len(zones))[::-1]  # highest score on top
    for row, z in zip(y, zones):
        left = 0.0
        for name, color in COMPONENTS:
            seg = weights[name] * z["subscores"][name]
            ax.barh(row, seg, left=left, height=0.68, color=color,
                    edgecolor=SURFACE, linewidth=1.4, zorder=2)
            left += seg
        ax.text(left + 1.2, row, f"{z['score']:.0f}", va="center", ha="left",
                fontsize=9, fontweight="bold", color=INK,
                fontvariant="small-caps")

    labels = [f"{KIND_ABBR[z['kind']]}  {z['low']:.0f}–{z['high']:.0f}" for z in zones]
    ax.set_yticks(y)
    ax.set_yticklabels(labels, fontsize=9, color=INK2, fontfamily="monospace")
    ax.set_title(sym, fontsize=12, fontweight="bold", color=INK, loc="left", pad=8)
    ax.set_xlim(0, 100)
    ax.set_facecolor(SURFACE)
    ax.grid(axis="x", color=GRID, zorder=0)
    ax.tick_params(colors=MUTED, labelsize=8)
    for s in ("top", "right", "left"):
        ax.spines[s].set_visible(False)
    ax.spines["bottom"].set_color("#c3c2b7")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config.yaml")
    ap.add_argument("--symbols", default="KO,MRVL,AMD")
    ap.add_argument("--top", type=int, default=8)
    ap.add_argument("--out", default="reports/phase4_score_breakdown.png")
    args = ap.parse_args()

    cfg = yaml.safe_load(Path(args.config).read_text())
    store = Store(cfg["data"]["db_path"])
    sc = cfg["scoring"]
    weights = sc["weights"]
    dp = dict(n=cfg["pivots"]["n_bars"], atr_period=cfg["volatility"]["atr_period"],
              tolerance=cfg["clustering"]["atr_tolerance"],
              min_touches=sc["min_touches"], lookback=cfg["detection"]["lookback_bars"])

    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    fig, axes = plt.subplots(1, len(symbols), figsize=(5.2 * len(symbols), 5.4),
                             squeeze=False)
    fig.patch.set_facecolor(SURFACE)

    for sym, ax in zip(symbols, axes[0]):
        df = store.get_bars(sym)
        res = detect_zones(df, **dp)
        scored = score_zones(res["zones"], res["df"], res["atr"],
                             weights, sc["params"], atr_pct=res["atr_pct"])
        panel(ax, sym, scored, weights, args.top)

    # Legend (always present — identity is never color-alone).
    handles = [Patch(facecolor=c, label=f"{n}  (w{weights[n]})") for n, c in COMPONENTS]
    fig.legend(handles=handles, loc="lower center", ncol=len(COMPONENTS),
               frameon=False, fontsize=9, labelcolor=INK2,
               bbox_to_anchor=(0.5, -0.02))
    fig.suptitle("Phase 4 — what builds each zone's score  "
                 "(segment = weight × sub-score; bar total = 0–100 composite)",
                 fontsize=13, fontweight="bold", color=INK, x=0.01, ha="left")
    fig.tight_layout(rect=[0, 0.05, 1, 0.96])
    Path(args.out).parent.mkdir(exist_ok=True)
    fig.savefig(args.out, dpi=140, facecolor=SURFACE, bbox_inches="tight")
    plt.close(fig)
    print(f"Wrote {args.out}")


if __name__ == "__main__":
    main()
