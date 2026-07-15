"""Score support/resistance zones on a 0-100 composite.

Six sub-scores, each normalized to [0,1], combined with the weights in
config.yaml (which sum to 100):

  touches     more touches = stronger, with diminishing returns (log/capped)
  bounce      average rejection strength — how far price moved AWAY after a touch
  angle       V-shape quality — min(move_in, move_out); enforces a symmetric V
  psych       proximity to a round number (boost-only, price-scaled hierarchy)
  containment rarity of CLOSES beyond the zone (a wick through that closes back
              inside is evidence of strength, not weakness)
  recency     exponential decay on bars since the most recent touch

Each function is pure so the components can be unit-tested in isolation.
"""

from __future__ import annotations

import math
from statistics import mean
from typing import List

import pandas as pd

# Round-number hierarchy: (step, weight). A level on a multiple of 100 is a
# stronger psychological anchor than one on a multiple of 5.
_PSYCH_STEPS = [(100, 1.0), (50, 0.8), (25, 0.6), (10, 0.5), (5, 0.35), (1, 0.2)]


def touch_score(touches: int, cap: int) -> float:
    """Saturating log score: min_touches -> low, `cap`+ touches -> 1.0."""
    if touches <= 1:
        return 0.0
    return min(1.0, math.log(touches) / math.log(cap))


def psych_score(center: float, tol: float) -> float:
    """Proximity of `center` to the nearest meaningful round level, in [0,1].

    Only round steps that are a meaningful fraction of the price are considered
    (so $1 increments don't matter on a $900 stock). `tol` is the distance over
    which proximity decays to zero.
    """
    if center <= 0 or tol <= 0:
        return 0.0
    best = 0.0
    for step, weight in _PSYCH_STEPS:
        if step < 0.004 * center:      # too fine to be psychologically meaningful here
            continue
        nearest = round(center / step) * step
        prox = max(0.0, 1.0 - abs(center - nearest) / tol)
        best = max(best, weight * prox)
    return min(1.0, best)


def recency_score(age_bars: int, halflife_bars: float) -> float:
    """Exponential decay: age 0 -> 1.0, age == halflife -> 0.5."""
    if halflife_bars <= 0:
        return 0.0
    return float(0.5 ** (max(0, age_bars) / halflife_bars))


def _pivot_moves(df: pd.DataFrame, piv: dict, bars: int):
    """Return (move_in, move_out) in dollars for a pivot: the price reach into
    the pivot over the prior `bars`, and away from it over the next `bars`."""
    i = piv["idx"]
    highs = df["high"].to_numpy(dtype=float)
    lows = df["low"].to_numpy(dtype=float)
    base = piv["price"]
    left_slice = slice(max(0, i - bars), i)
    right_slice = slice(i + 1, i + 1 + bars)
    if piv["kind"] == "low":
        left, right = highs[left_slice], highs[right_slice]
        move_in = (left.max() - base) if left.size else 0.0
        move_out = (right.max() - base) if right.size else 0.0
    else:  # high pivot
        left, right = lows[left_slice], lows[right_slice]
        move_in = (base - left.min()) if left.size else 0.0
        move_out = (base - right.min()) if right.size else 0.0
    return max(0.0, move_in), max(0.0, move_out)


def containment_score(df: pd.DataFrame, zone: dict, atr: float, buffer_atr: float) -> float:
    """held / (held + broke) over bars that pierced the zone.

    A bar pierces a support zone if its low reaches the zone; it "broke" if it
    also CLOSED below the zone (minus a small ATR buffer), else it "held"
    (wick-through, close back inside). Mirror for resistance. Mixed/flip zones
    are scored support-style. Neutral 0.5 if never pierced.
    """
    lo, hi = zone["low"], zone["high"]
    buf = buffer_atr * atr
    low = df["low"].to_numpy(dtype=float)
    high = df["high"].to_numpy(dtype=float)
    close = df["close"].to_numpy(dtype=float)

    if zone["kind"] == "resistance":
        pierced = high >= lo
        broke = pierced & (close > hi + buf)
    else:  # support or mixed
        pierced = low <= hi
        broke = pierced & (close < lo - buf)

    n_pierced = int(pierced.sum())
    if n_pierced == 0:
        return 0.5
    return 1.0 - int(broke.sum()) / n_pierced


def score_zone(zone: dict, df: pd.DataFrame, atr: float, weights: dict,
               params: dict, last_idx: int | None = None,
               atr_pct: float | None = None) -> dict:
    """Return a copy of `zone` with 'score' (0-100) and per-component 'subscores'.

    `atr_pct` (ATR / current price) is the volatility scale for bounce/angle;
    moves are measured as a fraction of each pivot's OWN price so a bounce from a
    year ago at a lower price isn't crushed by today's larger dollar ATR.
    """
    members = zone["members"]
    if atr_pct is None:
        last_close = float(df["close"].iloc[-1])
        atr_pct = (atr / last_close) if last_close else 0.0

    ts = touch_score(zone["touches"], params["touch_cap"])

    bounces, angles = [], []
    for m in members:
        mi, mo = _pivot_moves(df, m, params["bounce_bars"])
        base = m["price"]
        if atr_pct > 0 and base > 0:
            bounces.append(min(1.0, (mo / base) / (atr_pct * params["bounce_target_atr"])))
            angles.append(min(1.0, (min(mi, mo) / base) / (atr_pct * params["angle_target_atr"])))
    bs = mean(bounces) if bounces else 0.0
    ang = mean(angles) if angles else 0.0

    tol = max(zone["width"] / 2, params["psych_tol_pct"] * zone["center"])
    ps = psych_score(zone["center"], tol)

    cs = containment_score(df, zone, atr, params["break_buffer_atr"])

    if last_idx is None:
        last_idx = len(df) - 1
    age = last_idx - max(m["idx"] for m in members)
    rs = recency_score(age, params["recency_halflife_bars"])

    subs = {"touches": ts, "bounce": bs, "angle": ang,
            "psych": ps, "containment": cs, "recency": rs}
    total = sum(weights[k] * subs[k] for k in weights)
    return {
        **zone,
        "score": round(total, 1),
        "subscores": {k: round(v, 3) for k, v in subs.items()},
    }


def score_zones(zones: List[dict], df: pd.DataFrame, atr: float,
                weights: dict, params: dict, atr_pct: float | None = None) -> List[dict]:
    """Score every zone and return them sorted by score descending."""
    last_idx = len(df) - 1
    if atr_pct is None:
        last_close = float(df["close"].iloc[-1])
        atr_pct = (atr / last_close) if last_close else 0.0
    scored = [score_zone(z, df, atr, weights, params, last_idx, atr_pct) for z in zones]
    return sorted(scored, key=lambda z: z["score"], reverse=True)
