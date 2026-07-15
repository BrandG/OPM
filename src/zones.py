"""Cluster fractal pivots into support/resistance zones.

Clustering is volatility-adjusted AND price-relative: two pivots belong to the
same zone if their fractional price gap is within `tolerance * ATR%`, where
ATR% = ATR / price. This scales the tolerance both with each stock's volatility
(via ATR%) and with the price level of the pivots themselves — so a pivot from a
year ago at $60 is not merged using a dollar width calibrated to today's $230.
Using a single absolute `tolerance * ATR` (current ATR) over a long, trending
history over-merges old low-priced pivots into spuriously fat zones.

The merge is greedy over price-sorted pivots and *anchored* — a pivot joins the
current zone only if it is within tolerance of the zone's lowest member. That
bounds each zone's width and prevents chain-drift (where each pivot is close to
its neighbor but the zone spans a huge range).
"""

from __future__ import annotations

from typing import List, Optional

import pandas as pd

from src.pivots import find_pivots
from src.volatility import wilder_atr


def _make_zone(members: List[dict], atr: float) -> dict:
    prices = [m["price"] for m in members]
    lo, hi = min(prices), max(prices)
    n_low = sum(1 for m in members if m["kind"] == "low")
    n_high = len(members) - n_low
    if n_low > n_high:
        kind = "support"
    elif n_high > n_low:
        kind = "resistance"
    else:
        kind = "mixed"  # level that has acted as both — a flip zone
    width = hi - lo
    return {
        "kind": kind,
        "low": lo,
        "high": hi,
        "center": sum(prices) / len(prices),
        "touches": len(members),
        "n_low": n_low,
        "n_high": n_high,
        "width": width,
        "width_atr": (width / atr) if atr else None,
        "first_touch": min(m["date"] for m in members),
        "last_touch": max(m["date"] for m in members),
        "members": members,
    }


def cluster_pivots(pivots: List[dict], *, tol_frac: float, atr: float,
                   min_touches: int = 1) -> List[dict]:
    """Greedily cluster pivots into zones, keeping those with >= min_touches.

    A pivot joins the current zone if its fractional gap above the zone's lowest
    member, (price - anchor) / anchor, is within `tol_frac`. `atr` is used only
    to report each zone's width in ATR units. Returns zones sorted by center
    price ascending.
    """
    if not pivots or tol_frac <= 0:
        return []
    ordered = sorted(pivots, key=lambda p: p["price"])

    zones: List[dict] = []
    cluster = [ordered[0]]
    anchor = ordered[0]["price"]
    for p in ordered[1:]:
        if anchor > 0 and (p["price"] - anchor) / anchor <= tol_frac:
            cluster.append(p)
        else:
            zones.append(_make_zone(cluster, atr))
            cluster = [p]
            anchor = p["price"]
    zones.append(_make_zone(cluster, atr))

    return [z for z in zones if z["touches"] >= min_touches]


def detect_zones(df: pd.DataFrame, *, n: int, atr_period: int,
                 tolerance: float, min_touches: int = 2,
                 lookback: Optional[int] = None) -> dict:
    """End-to-end: bars -> pivots -> zones for one symbol.

    If `lookback` is set, only the trailing `lookback` bars are used for
    detection (ATR, pivots, zones) — recent levels are what matter for a swing
    trade, and it keeps current ATR representative of the current price regime.
    Full history stays in the cache for backtesting.

    Returns {atr, atr_pct, tol_frac, pivots, zones, df} where df is the window
    actually used (so pivot indices align with it for plotting).
    """
    win = df if not lookback else df.iloc[-lookback:]
    atr = float(wilder_atr(win, atr_period).iloc[-1])
    last_close = float(win["close"].iloc[-1])
    atr_pct = (atr / last_close) if last_close else 0.0
    tol_frac = tolerance * atr_pct
    pivots = find_pivots(win, n)
    zones = cluster_pivots(pivots, tol_frac=tol_frac, atr=atr, min_touches=min_touches)
    return {"atr": atr, "atr_pct": atr_pct, "tol_frac": tol_frac,
            "pivots": pivots, "zones": zones, "df": win}
