"""Turn scored zones into long-only bracket setups.

For a symbol at the current price, find the nearest strong support below and the
nearest strong resistance above, then build the bracket:

    entry  = support_high + entry_buffer_atr * ATR   (slightly above support)
    stop   = support_low  - stop_atr_buffer  * ATR   (just below the zone; NOT
                                                       the next support down)
    target = resistance_low - target_buffer_atr * ATR (just below resistance)

Setups are gated on corridor width and reward/risk, sized with fractional shares
against a risk budget, and flagged 'armed' when price is close enough to support
to place the entry. Blue-sky breakouts (no resistance above) are skipped —
there's no S/R target to aim at.

All pure functions; the live/scan layers just supply price + config.
"""

from __future__ import annotations

from typing import List, Optional, Tuple


def _recent_above_frac(closes, level: float) -> float:
    """Fraction of `closes` that sit above `level` (empty -> 0)."""
    closes = list(closes)
    if not closes:
        return 0.0
    return sum(1 for c in closes if c > level) / len(closes)


def find_bracketing_zones(zones: List[dict], price: float, min_score: float,
                          closes=None, confirm_bars: int = 15,
                          min_above: float = 0.5
                          ) -> Tuple[Optional[dict], Optional[dict]]:
    """Nearest strong support fully below price and resistance fully above it.

    A below-price zone only qualifies as SUPPORT if price is genuinely pulling
    back to it from above — i.e. at least `min_above` of the last `confirm_bars`
    closes sat above the zone. This rejects zones price is *rising into from
    below* (which act as resistance, not support). Pass `closes` (the recent
    close series) to enable the guard; omit it to select by position only.
    """
    strong = [z for z in zones if z.get("score", 0) >= min_score]
    below = [z for z in strong if z["high"] < price]
    above = [z for z in strong if z["low"] > price]

    if closes is not None:
        recent = list(closes)[-confirm_bars:]
        below = [z for z in below if _recent_above_frac(recent, z["high"]) >= min_above]

    support = max(below, key=lambda z: z["high"]) if below else None
    resistance = min(above, key=lambda z: z["low"]) if above else None
    return support, resistance


def size_position(entry: float, stop: float, equity: float, risk_pct: float,
                  max_position_pct: float) -> dict:
    """Fractional-share sizing: risk `risk_pct` of equity, capped at
    `max_position_pct` of equity per position."""
    per_share_risk = entry - stop
    if per_share_risk <= 0 or entry <= 0:
        return {"shares": 0.0, "position_value": 0.0, "risk_dollars": 0.0,
                "position_capped": False}
    risk_dollars = equity * risk_pct
    shares = risk_dollars / per_share_risk
    position_value = shares * entry
    cap = equity * max_position_pct
    capped = False
    if position_value > cap:
        shares = cap / entry
        position_value = shares * entry
        risk_dollars = shares * per_share_risk
        capped = True
    return {
        "shares": round(shares, 4),
        "position_value": round(position_value, 2),
        "risk_dollars": round(risk_dollars, 2),
        "position_capped": capped,
    }


def decline_metrics(closes, ret_bars: int = 42, dd_bars: int = 60) -> dict:
    """How hard has this name been falling INTO the signal? `ret_42b` is the
    ~2-month return; `dd_60b` is the drawdown from the 60-bar high.

    REPORTING ONLY — deliberately not a gate. Tested 2026-07-29 as a hard
    falling-knife filter across 2547 trades and every threshold was neutral or
    harmful (see docs/PROJECT_LOG.md); the buckets that looked bad had bootstrap
    CIs spanning zero. But the backtest is survivorship-blind to knives that kept
    falling, so the metric is surfaced for human judgement instead of acted on.
    Same posture as target_dist_atr. Returns None values when history is short.
    """
    if closes is None or len(closes) < dd_bars + 1:
        return {"ret_42b": None, "dd_60b": None}
    c = [float(x) for x in closes]
    ret = c[-1] / c[-(ret_bars + 1)] - 1.0 if c[-(ret_bars + 1)] else None
    window = c[-dd_bars:]
    peak = max(window)
    return {"ret_42b": round(ret, 4) if ret is not None else None,
            "dd_60b": round(c[-1] / peak - 1.0, 4) if peak else None}


def build_setup(symbol: str, zones: List[dict], price: float, atr: float,
                t: dict, closes=None, trend: str = None) -> dict:
    """Build a bracket setup dict. `t` is the config 'trade' block.

    `closes` (recent close series) enables the pullback-from-above guard on
    support selection. `trend` ('up'/'down'), when the `require_trend` gate is on,
    restricts longs to uptrends. Always returns a dict with 'passed'/'reasons'.
    """
    base = {"symbol": symbol.upper(), "price": round(price, 2), "atr": round(atr, 2),
            "passed": False, "armed": False, "reasons": [], "trade_score": 0.0,
            **decline_metrics(closes)}

    if t.get("require_trend") and trend is not None and trend != "up":
        return {**base, "reasons": ["not_uptrend"], "support": None, "resistance": None}

    support, resistance = find_bracketing_zones(
        zones, price, t["min_zone_score"], closes=closes,
        confirm_bars=t.get("entry_confirm_bars", 15),
        min_above=t.get("min_recent_above", 0.5))
    if support is None:
        # Distinguish "price is climbing into a level from below" from "no zone
        # below at all" — the former is the dangerous buy-into-resistance case.
        strong_below = [z for z in zones
                        if z.get("score", 0) >= t["min_zone_score"] and z["high"] < price]
        reason = "approaching_from_below" if strong_below else "no_support_below"
        return {**base, "reasons": [reason], "support": None, "resistance": None}
    if resistance is None:
        # Blue-sky breakout: no overhead S/R to target.
        return {**base, "reasons": ["no_resistance_above"],
                "support": _z(support), "resistance": None}

    entry = support["high"] + t["entry_buffer_atr"] * atr
    stop = support["low"] - t["stop_atr_buffer"] * atr
    target = resistance["low"] - t["target_buffer_atr"] * atr

    reasons: List[str] = []
    if not (stop < entry < target):
        reasons.append("degenerate_bracket")

    per_share_risk = entry - stop
    corridor_pct = (resistance["low"] - support["high"]) / price
    rr = (target - entry) / per_share_risk if per_share_risk > 0 else 0.0
    # Reachability in ATR units: how many ATRs of travel the target demands. A far
    # resistance yields a big headline R/R the trade can't realise inside the hold
    # window (it time-stops well short), so gate on it — see max_target_atr below.
    target_dist_atr = (target - entry) / atr if atr > 0 else 0.0
    dist_pct = (price - support["high"]) / price          # how far price sits above support top
    armed = support["high"] < price <= support["high"] * (1 + t["max_entry_dist_pct"])

    if corridor_pct < t["min_corridor_pct"]:
        reasons.append("corridor_narrow")
    if rr < t["min_reward_risk"]:
        reasons.append("rr_low")
    max_tgt = t.get("max_target_atr")
    if max_tgt and target_dist_atr > max_tgt:
        reasons.append("target_unreachable")            # target too far to reach in the hold

    sizing = size_position(entry, stop, t["account_equity"], t["risk_pct"],
                           t["max_position_pct"])
    proximity = max(0.0, 1 - dist_pct / t["max_entry_dist_pct"]) if t["max_entry_dist_pct"] else 0.0
    trade_score = round(100 * (
        0.30 * support["score"] / 100
        + 0.20 * resistance["score"] / 100
        + 0.25 * min(rr / 3, 1)
        + 0.15 * proximity
        + 0.10 * min(corridor_pct / 0.10, 1)
    ), 1)

    return {
        **base,
        "passed": len(reasons) == 0,
        "armed": armed,
        "reasons": reasons,
        "support": _z(support),
        "resistance": _z(resistance),
        "entry": round(entry, 2),
        "stop": round(stop, 2),
        "target": round(target, 2),
        "rr": round(rr, 2),
        "corridor_pct": round(corridor_pct, 4),
        "target_dist_atr": round(target_dist_atr, 2),
        "risk_pct": round(per_share_risk / entry, 4),
        "reward_pct": round((target - entry) / entry, 4),
        "dist_to_support_pct": round(dist_pct, 4),
        "trade_score": trade_score,
        **sizing,
    }


def _z(zone: dict) -> dict:
    """Compact zone summary for a setup record."""
    return {"kind": zone["kind"], "low": round(zone["low"], 2),
            "high": round(zone["high"], 2), "score": zone["score"],
            "touches": zone["touches"]}


# --------------------------------------------------------------------------
# Short side — the mirror image: sell rallies INTO resistance, target support.
# --------------------------------------------------------------------------

def _recent_below_frac(closes, level: float) -> float:
    closes = list(closes)
    if not closes:
        return 0.0
    return sum(1 for c in closes if c < level) / len(closes)


def find_short_zones(zones: List[dict], price: float, min_score: float,
                     closes=None, confirm_bars: int = 15, min_above: float = 0.5
                     ) -> Tuple[Optional[dict], Optional[dict]]:
    """Nearest strong resistance above price (to short) and support below (target).

    Mirror of the long guard: a resistance only qualifies if price is rallying UP
    into it from below — at least `min_above` of recent closes sit BELOW the zone
    (price hasn't broken above it). Rejects zones price has already broken out over.
    """
    strong = [z for z in zones if z.get("score", 0) >= min_score]
    above = [z for z in strong if z["low"] > price]     # resistance candidates
    below = [z for z in strong if z["high"] < price]    # support targets

    if closes is not None:
        recent = list(closes)[-confirm_bars:]
        above = [z for z in above if _recent_below_frac(recent, z["low"]) >= min_above]

    resistance = min(above, key=lambda z: z["low"]) if above else None
    support = max(below, key=lambda z: z["high"]) if below else None
    return resistance, support


def build_short_setup(symbol: str, zones: List[dict], price: float, atr: float,
                      t: dict, closes=None, trend: str = None) -> dict:
    """Mirror of build_setup for a short:
        entry  = resistance_low  - entry_buffer_atr * ATR  (short just below resistance)
        stop   = resistance_high + stop_atr_buffer  * ATR  (above the zone)
        target = support_high     + target_buffer_atr* ATR  (cover just above support)
    """
    base = {"symbol": symbol.upper(), "price": round(price, 2), "atr": round(atr, 2),
            "side": "short", "passed": False, "armed": False, "reasons": [],
            "trade_score": 0.0}

    if t.get("require_trend") and trend is not None and trend != "down":
        return {**base, "reasons": ["not_downtrend"], "support": None, "resistance": None}

    resistance, support = find_short_zones(
        zones, price, t["min_zone_score"], closes=closes,
        confirm_bars=t.get("entry_confirm_bars", 15),
        min_above=t.get("min_recent_above", 0.5))
    if resistance is None:
        strong_above = [z for z in zones
                        if z.get("score", 0) >= t["min_zone_score"] and z["low"] > price]
        reason = "breaking_out_above" if strong_above else "no_resistance_above"
        return {**base, "reasons": [reason], "support": None, "resistance": None}
    if support is None:
        return {**base, "reasons": ["no_support_below"],
                "resistance": _z(resistance), "support": None}

    entry = resistance["low"] - t["entry_buffer_atr"] * atr
    stop = resistance["high"] + t["stop_atr_buffer"] * atr
    target = support["high"] + t["target_buffer_atr"] * atr

    reasons: List[str] = []
    if not (target < entry < stop):
        reasons.append("degenerate_bracket")
    per_share_risk = stop - entry
    corridor_pct = (resistance["low"] - support["high"]) / price
    rr = (entry - target) / per_share_risk if per_share_risk > 0 else 0.0
    target_dist_atr = (entry - target) / atr if atr > 0 else 0.0   # travel to cover, in ATRs
    dist_pct = (resistance["low"] - price) / price
    armed = resistance["low"] * (1 - t["max_entry_dist_pct"]) <= price < resistance["low"]

    if corridor_pct < t["min_corridor_pct"]:
        reasons.append("corridor_narrow")
    if rr < t["min_reward_risk"]:
        reasons.append("rr_low")
    max_tgt = t.get("max_target_atr")
    if max_tgt and target_dist_atr > max_tgt:
        reasons.append("target_unreachable")

    proximity = max(0.0, 1 - dist_pct / t["max_entry_dist_pct"]) if t["max_entry_dist_pct"] else 0.0
    trade_score = round(100 * (
        0.30 * resistance["score"] / 100
        + 0.20 * support["score"] / 100
        + 0.25 * min(rr / 3, 1)
        + 0.15 * proximity
        + 0.10 * min(corridor_pct / 0.10, 1)
    ), 1)

    return {
        **base,
        "passed": len(reasons) == 0,
        "armed": armed,
        "reasons": reasons,
        "resistance": _z(resistance),
        "support": _z(support),
        "entry": round(entry, 2),
        "stop": round(stop, 2),
        "target": round(target, 2),
        "rr": round(rr, 2),
        "corridor_pct": round(corridor_pct, 4),
        "target_dist_atr": round(target_dist_atr, 2),
        "risk_pct": round(per_share_risk / entry, 4),
        "reward_pct": round((entry - target) / entry, 4),
        "dist_to_resistance_pct": round(dist_pct, 4),
        "trade_score": trade_score,
    }
