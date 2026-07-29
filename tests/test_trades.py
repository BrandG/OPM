from src.trades import (find_bracketing_zones, size_position, build_setup,
                        decline_metrics)


def _zone(low, high, score, kind="support", touches=3):
    return {"low": low, "high": high, "center": (low + high) / 2, "kind": kind,
            "score": score, "touches": touches}


T = {"min_zone_score": 55, "entry_buffer_atr": 0.05, "stop_atr_buffer": 0.35,
     "target_buffer_atr": 0.10, "max_entry_dist_pct": 0.03, "min_corridor_pct": 0.03,
     "min_reward_risk": 2.0, "account_equity": 3585, "risk_pct": 0.01,
     "max_position_pct": 0.25}


def test_find_bracketing_picks_nearest_strong():
    zones = [
        _zone(90, 91, 60), _zone(95, 96, 70),      # supports below 100
        _zone(50, 51, 80),                          # weaker-position support far below
        _zone(110, 111, 65), _zone(120, 121, 60),   # resistances above
        _zone(97, 98, 40),                          # strong-position but low score -> ignored
    ]
    sup, res = find_bracketing_zones(zones, price=100, min_score=55)
    assert sup["high"] == 96      # nearest strong support below
    assert res["low"] == 110      # nearest strong resistance above


def test_find_bracketing_ignores_zone_containing_price():
    zones = [_zone(99, 101, 70)]  # price sits inside this zone
    sup, res = find_bracketing_zones(zones, price=100, min_score=55)
    assert sup is None and res is None


def test_size_position_risk_based_and_capped():
    # risk 1% of 3585 = 35.85; per-share risk 5 -> ~7.17 shares, value ~717.
    s = size_position(entry=100, stop=95, equity=3585, risk_pct=0.01, max_position_pct=0.25)
    assert abs(s["risk_dollars"] - 35.85) < 0.5
    assert abs(s["shares"] - 7.17) < 0.05
    assert not s["position_capped"]

    # Tight stop would demand a huge position -> capped at 25% of equity.
    s2 = size_position(entry=100, stop=99.9, equity=3585, risk_pct=0.01, max_position_pct=0.25)
    assert s2["position_capped"]
    assert abs(s2["position_value"] - 3585 * 0.25) < 1


def test_build_setup_clean_passes():
    # support 95-96, resistance 130-131, price 97 (armed, near support). ATR 2.
    zones = [_zone(95, 96, 70, "support"), _zone(130, 131, 68, "resistance")]
    s = build_setup("XYZ", zones, price=97.0, atr=2.0, t=T)
    assert s["passed"] and s["armed"]
    assert s["stop"] < s["entry"] < s["target"]
    assert s["rr"] >= 2.0
    assert s["shares"] > 0


def test_build_setup_rejects_low_rr():
    # resistance very close above support -> tiny reward vs stop distance.
    zones = [_zone(95, 96, 70, "support"), _zone(99, 100, 68, "resistance")]
    s = build_setup("XYZ", zones, price=97.0, atr=2.0, t=T)
    assert not s["passed"]
    assert "rr_low" in s["reasons"] or "corridor_narrow" in s["reasons"]


def test_target_reachability_gate():
    # Support 95-96, resistance far up at 130-131, ATR 2 -> target ~130.8, entry
    # ~96.1, so target is ~(130.8-96.1)/2 ≈ 17 ATRs away. Off by default: passes.
    zones = [_zone(95, 96, 70, "support"), _zone(130, 131, 68, "resistance")]
    off = build_setup("XYZ", zones, price=97.0, atr=2.0, t=T)
    assert off["passed"]
    assert off["target_dist_atr"] > 15                 # genuinely far in ATR terms

    # Turn the gate on with a 12-ATR ceiling -> the far target is unreachable.
    gated = build_setup("XYZ", zones, price=97.0, atr=2.0, t={**T, "max_target_atr": 12})
    assert not gated["passed"]
    assert "target_unreachable" in gated["reasons"]

    # A nearby resistance (target within the ceiling) still passes with the gate on.
    near = [_zone(95, 96, 70, "support"), _zone(108, 109, 68, "resistance")]
    ok = build_setup("XYZ", near, price=97.0, atr=2.0, t={**T, "max_target_atr": 12})
    assert ok["passed"]
    assert ok["target_dist_atr"] <= 12


def test_support_guard_rejects_rising_into_zone():
    # Zone 95-96 below price 97, but recent closes are mostly BELOW it: price is
    # climbing into it from underneath (resistance), not pulling back to it.
    zones = [_zone(95, 96, 70, "resistance"), _zone(130, 131, 68, "resistance")]
    rising = [88, 89, 90, 91, 92, 93, 94, 95, 96, 97]  # only the last clears 96
    sup, _ = find_bracketing_zones(zones, 97.0, min_score=55, closes=rising)
    assert sup is None

    # Same zone, but price spent most of the window ABOVE it then dipped back:
    pullback = [102, 103, 101, 100, 99, 98, 99, 100, 98, 97]  # all above 96
    sup2, _ = find_bracketing_zones(zones, 97.0, min_score=55, closes=pullback)
    assert sup2 is not None and sup2["high"] == 96


def test_build_setup_flags_approaching_from_below():
    zones = [_zone(95, 96, 70, "support"), _zone(130, 131, 68, "resistance")]
    rising = [88, 89, 90, 91, 92, 93, 94, 95, 96, 97]
    s = build_setup("XYZ", zones, price=97.0, atr=2.0, t=T, closes=rising)
    assert not s["passed"]
    assert s["reasons"] == ["approaching_from_below"]


def test_build_setup_blue_sky_skipped():
    # Only supports below price, nothing above -> blue sky.
    zones = [_zone(95, 96, 70, "support"), _zone(80, 81, 65, "support")]
    s = build_setup("XYZ", zones, price=120.0, atr=2.0, t=T)
    assert not s["passed"]
    assert s["reasons"] == ["no_resistance_above"]
    assert s["resistance"] is None


def test_decline_metrics_measures_fall_into_signal():
    # 100 -> 70 over the last 42 bars, with a 60-bar peak of 120.
    # 42 bars back from the final close must land on 100, so 100 needs 42 slots.
    closes = [120.0] * 20 + [100.0] * 42 + [70.0]
    m = decline_metrics(closes)
    assert m["ret_42b"] == round(70 / 100 - 1, 4)        # -30% over ~2 months
    assert m["dd_60b"] == round(70 / 120 - 1, 4)         # -41.7% off the 60-bar high


def test_decline_metrics_none_on_short_history():
    assert decline_metrics([1.0] * 10) == {"ret_42b": None, "dd_60b": None}
    assert decline_metrics(None) == {"ret_42b": None, "dd_60b": None}


def test_build_setup_carries_decline_metrics_without_gating():
    """The metric is reported, never acted on: a steep decline must NOT block a
    setup that otherwise passes (gating on it showed no edge — PROJECT_LOG)."""
    zones = [_zone(95, 96, 70), _zone(110, 111, 65)]
    closes = [200.0] * 20 + [140.0] * 40 + [100.0] * 2   # brutal decline into now
    s = build_setup("KNIFE", zones, 98, 2.0, T, closes=closes)
    assert s["passed"] is True                            # still tradeable
    assert s["ret_42b"] < -0.20                           # and flagged as steep
    assert s["dd_60b"] < -0.20
