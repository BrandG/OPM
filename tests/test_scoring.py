import pandas as pd

from src.scoring import (
    touch_score, psych_score, recency_score, containment_score, score_zone,
)


def test_touch_score_saturates():
    assert touch_score(1, cap=6) == 0.0
    assert touch_score(2, cap=6) < touch_score(3, cap=6) < touch_score(5, cap=6)
    assert touch_score(6, cap=6) == 1.0
    assert touch_score(20, cap=6) == 1.0  # capped


def test_psych_score_prefers_round_and_is_price_scaled():
    # On round 100 -> high; off at 97.34 -> low.
    assert psych_score(100.0, tol=0.5) > 0.9
    assert psych_score(97.34, tol=0.5) < 0.2
    # $0.50 off on a $900 stock is still "on" 900 (tol scales with price upstream,
    # here we pass a price-scaled tol) and 100-multiple outranks smaller steps.
    assert psych_score(900.5, tol=4.5) > 0.8
    # A fine $1 offset on a big stock shouldn't score as a strong anchor.
    assert psych_score(903.0, tol=4.5) < psych_score(900.5, tol=4.5)


def test_recency_score_halflife():
    assert recency_score(0, 63) == 1.0
    assert abs(recency_score(63, 63) - 0.5) < 1e-9
    assert recency_score(126, 63) < 0.3


def _df(rows):
    idx = pd.date_range("2026-01-01", periods=len(rows), freq="D")
    return pd.DataFrame(rows, index=idx)


def test_containment_rewards_wick_through_close_inside():
    # Support zone 99-101. Bars dip in but CLOSE back above -> held.
    held_df = _df([{"low": 98.5, "high": 105, "close": 103, "open": 100, "volume": 1}] * 5)
    zone = {"kind": "support", "low": 99.0, "high": 101.0}
    assert containment_score(held_df, zone, atr=2.0, buffer_atr=0.1) == 1.0

    # Same zone but bars CLOSE below -> broke.
    broke_df = _df([{"low": 98.5, "high": 105, "close": 95, "open": 100, "volume": 1}] * 5)
    assert containment_score(broke_df, zone, atr=2.0, buffer_atr=0.1) == 0.0


def test_containment_neutral_when_never_pierced():
    df = _df([{"low": 200, "high": 210, "close": 205, "open": 205, "volume": 1}] * 5)
    zone = {"kind": "support", "low": 99.0, "high": 101.0}  # far below price
    assert containment_score(df, zone, atr=2.0, buffer_atr=0.1) == 0.5


WEIGHTS = {"touches": 25, "bounce": 25, "angle": 15, "psych": 10,
           "containment": 15, "recency": 10}
PARAMS = {"touch_cap": 6, "bounce_bars": 5, "bounce_target_atr": 1.5,
          "angle_target_atr": 1.0, "break_buffer_atr": 0.1,
          "recency_halflife_bars": 63, "psych_tol_pct": 0.005}


def test_score_zone_is_bounded_and_has_all_subscores():
    # Build a V around a support low at index 5.
    lows = [110, 105, 102, 101, 100, 90, 100, 101, 103, 106, 110]
    highs = [h + 2 for h in lows]
    df = _df([{"low": l, "high": h, "close": (l + h) / 2, "open": l, "volume": 1}
              for l, h in zip(lows, highs)])
    member = {"idx": 5, "date": df.index[5], "price": 90.0, "kind": "low"}
    zone = {"kind": "support", "low": 90.0, "high": 90.0, "center": 90.0,
            "touches": 2, "width": 0.0, "members": [member, member]}
    scored = score_zone(zone, df, atr=5.0, weights=WEIGHTS, params=PARAMS)
    assert 0 <= scored["score"] <= 100
    assert set(scored["subscores"]) == set(WEIGHTS)
    # Sharp V with a deep drop/recovery -> meaningful bounce & angle.
    assert scored["subscores"]["bounce"] > 0
    assert scored["subscores"]["angle"] > 0
