from src.trend import sma, trend_state
from src.trades import build_setup


def test_sma_and_insufficient_history():
    assert sma([1, 2, 3, 4], 2) == 3.5
    assert sma([1, 2], 5) is None


def test_trend_state_up_and_down():
    up = list(range(1, 60))                     # steadily rising
    assert trend_state(up, period=20) == "up"
    down = list(range(60, 1, -1))               # steadily falling
    assert trend_state(down, period=20) == "down"


def test_trend_state_neutral_when_short():
    assert trend_state([1, 2, 3], period=20) == "up"   # not enough data -> neutral


def _zone(low, high, score, kind="support"):
    return {"low": low, "high": high, "center": (low + high) / 2, "kind": kind,
            "score": score, "touches": 3}


def test_build_setup_trend_gate_blocks_long_in_downtrend():
    t = {"min_zone_score": 55, "entry_buffer_atr": 0.05, "stop_atr_buffer": 0.35,
         "target_buffer_atr": 0.10, "max_entry_dist_pct": 0.03, "min_corridor_pct": 0.03,
         "min_reward_risk": 2.0, "require_trend": True,
         "account_equity": 3585, "risk_pct": 0.01, "max_position_pct": 0.25}
    zones = [_zone(95, 96, 70), _zone(130, 131, 68, "resistance")]
    s = build_setup("XYZ", zones, price=97.0, atr=2.0, t=t, trend="down")
    assert not s["passed"] and s["reasons"] == ["not_uptrend"]

    # Same setup, uptrend -> not blocked by the trend gate.
    s2 = build_setup("XYZ", zones, price=97.0, atr=2.0, t=t, trend="up",
                     closes=[102, 101, 100, 99, 98, 99, 100, 98, 97, 97])
    assert s2["reasons"] != ["not_uptrend"]
