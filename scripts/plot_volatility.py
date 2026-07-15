"""Visual proof of the Phase 2 volatility ranking.

Produces two PNGs under reports/:

  phase2_ranking.png  -- the ATR% scoreboard, plus the per-bar true-range%
                         distribution that the ATR average is built from.
  phase2_bars.png     -- small-multiple high/low range charts, one per symbol,
                         so the physical bar heights (relative to price) are
                         visible side by side.

Reads bars straight from the local cache. Reusable for the Phase 3 zone-overlay
charts later.

Usage:
    python scripts/plot_volatility.py [--config config.yaml]
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
from src.volatility import true_range, wilder_atr, rank_universe

BG = "#ffffff"
FG = "#1f2933"
GRID = "#e4e7eb"


def _load(cfg, top=None):
    store = Store(cfg["data"]["db_path"])
    syms = []
    for line in Path(cfg["universe"]["source_file"]).read_text().splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            syms.append(line.upper())
    period = cfg["volatility"]["atr_period"]
    min_bars = cfg["volatility"].get("min_bars") or period
    ranked = rank_universe(store, syms, period=period, min_bars=min_bars)
    if top:
        ranked = ranked.head(top).reset_index(drop=True)

    data = {}
    for _, row in ranked.iterrows():
        df = store.get_bars(row["symbol"])
        tr_pct = (true_range(df) / df["close"]).to_numpy() * 100
        data[row["symbol"]] = {
            "df": df,
            "tr_pct": tr_pct,
            "atr_pct": row["atr_pct"] * 100,
            "last_close": row["last_close"],
        }
    return ranked, data, period


def _color_map(atr_pcts):
    lo, hi = min(atr_pcts), max(atr_pcts)
    norm = plt.Normalize(lo, hi)
    cmap = plt.cm.plasma
    return {i: cmap(norm(v)) for i, v in enumerate(atr_pcts)}, cmap, norm


def plot_ranking(ranked, data, period, out):
    order = list(ranked["symbol"])            # already sorted desc by atr_pct
    atr_pcts = [data[s]["atr_pct"] for s in order]
    colors, cmap, norm = _color_map(atr_pcts)

    h = max(10, len(order) * 0.55)
    fig, (ax1, ax2) = plt.subplots(
        2, 1, figsize=(12, h), gridspec_kw={"height_ratios": [1, 1.25]}
    )
    fig.patch.set_facecolor(BG)

    # --- Panel 1: ATR% scoreboard (bars top-to-bottom = most volatile first) ---
    y = np.arange(len(order))[::-1]
    for i, sym in enumerate(order):
        ax1.barh(y[i], atr_pcts[i], color=colors[i], edgecolor="none", zorder=3)
        ax1.text(atr_pcts[i] + 0.15, y[i],
                 f"{atr_pcts[i]:.2f}%  ·  ${data[sym]['last_close']:,.2f}",
                 va="center", ha="left", fontsize=10, color=FG)
    ax1.set_yticks(y)
    ax1.set_yticklabels(order, fontsize=11, fontweight="bold")
    ax1.set_xlabel(f"ATR-{period} as % of price", fontsize=10, color=FG)
    ax1.set_title("Phase 2 — volatility ranking (the score)",
                  fontsize=13, fontweight="bold", color=FG, loc="left", pad=10)
    ax1.set_xlim(0, max(atr_pcts) * 1.28)

    # --- Panel 2: the raw material — every bar's true-range %, per symbol -------
    for i, sym in enumerate(order):
        tr = data[sym]["tr_pct"]
        ypos = y[i]
        jitter = (np.random.default_rng(i).random(len(tr)) - 0.5) * 0.5
        ax2.scatter(tr, np.full(len(tr), ypos) + jitter, s=18, alpha=0.45,
                    color=colors[i], edgecolor="none", zorder=2)
        ax2.scatter([data[sym]["atr_pct"]], [ypos], marker="D", s=90,
                    color=colors[i], edgecolor=FG, linewidth=1.2, zorder=4)
    ax2.set_yticks(y)
    ax2.set_yticklabels(order, fontsize=11, fontweight="bold")
    ax2.set_xlabel("Daily true range as % of price  (dots = each bar · diamond = ATR average)",
                   fontsize=10, color=FG)
    ax2.set_title("Why they ranked — the distribution the average summarizes",
                  fontsize=13, fontweight="bold", color=FG, loc="left", pad=10)
    ax2.set_xlim(left=0)

    for ax in (ax1, ax2):
        ax.set_facecolor(BG)
        ax.grid(axis="x", color=GRID, zorder=0)
        for s in ("top", "right", "left"):
            ax.spines[s].set_visible(False)
        ax.tick_params(colors=FG)

    sm = plt.cm.ScalarMappable(cmap=cmap, norm=norm)
    cb = fig.colorbar(sm, ax=[ax1, ax2], fraction=0.03, pad=0.02)
    cb.set_label("ATR%", color=FG)

    fig.suptitle("Support/Resistance Scanner · Phase 2 volatility proof",
                 fontsize=11, color="#7b8794", x=0.01, ha="left", y=0.995)
    fig.savefig(out, dpi=140, facecolor=BG, bbox_inches="tight")
    plt.close(fig)


def plot_bars(ranked, data, out, cols=6):
    order = list(ranked["symbol"])
    atr_pcts = [data[s]["atr_pct"] for s in order]
    colors, _, _ = _color_map(atr_pcts)

    rows = (len(order) + cols - 1) // cols
    fig, axes = plt.subplots(rows, cols, figsize=(cols * 3.2, rows * 2.4))
    fig.patch.set_facecolor(BG)
    axes = np.atleast_1d(axes).ravel()
    for ax in axes[len(order):]:
        ax.set_visible(False)
    for i, (sym, ax) in enumerate(zip(order, axes)):
        df = data[sym]["df"]
        x = np.arange(len(df))
        ax.vlines(x, df["low"].to_numpy(), df["high"].to_numpy(),
                  color=colors[i], linewidth=2.4, alpha=0.9)
        ax.plot(x, df["close"].to_numpy(), color=FG, linewidth=0.8, alpha=0.6)
        ax.set_title(f"{sym}   {data[sym]['atr_pct']:.1f}% ATR",
                     fontsize=12, fontweight="bold", color=FG, loc="left")
        ax.set_facecolor(BG)
        ax.grid(axis="y", color=GRID)
        for s in ("top", "right"):
            ax.spines[s].set_visible(False)
        ax.tick_params(colors=FG, labelsize=8)
        ax.set_xticks([])
    fig.suptitle("Daily high–low bars, same 45 sessions — bar height vs price IS the ATR%",
                 fontsize=13, fontweight="bold", color=FG, x=0.01, ha="left")
    fig.tight_layout(rect=[0, 0, 1, 0.96])
    fig.savefig(out, dpi=140, facecolor=BG, bbox_inches="tight")
    plt.close(fig)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config.yaml")
    ap.add_argument("--top", type=int, default=30,
                    help="plot only the top N most volatile (default 30)")
    args = ap.parse_args()
    cfg = yaml.safe_load(Path(args.config).read_text())

    out_dir = Path("reports")
    out_dir.mkdir(exist_ok=True)
    ranked, data, period = _load(cfg, top=args.top)

    plot_ranking(ranked, data, period, out_dir / "phase2_ranking.png")
    plot_bars(ranked, data, out_dir / "phase2_bars.png")
    print(f"Wrote {out_dir/'phase2_ranking.png'} and {out_dir/'phase2_bars.png'} "
          f"(top {len(ranked)})")


if __name__ == "__main__":
    main()
