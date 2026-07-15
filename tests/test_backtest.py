import numpy as np

from src.backtest import (
    _exit_on_bar, _exit_on_bar_short, _same_bar_after_fill, _close, summarize,
)


STOP, TGT = 95.0, 115.0


def test_exit_gap_down_through_stop():
    assert _exit_on_bar(o=90, h=92, l=89, stop=STOP, target=TGT) == ("stop", 90)


def test_exit_gap_up_through_target():
    assert _exit_on_bar(o=118, h=120, l=117, stop=STOP, target=TGT) == ("target", 118)


def test_exit_normal_stop_and_target():
    assert _exit_on_bar(o=100, h=101, l=94, stop=STOP, target=TGT) == ("stop", STOP)
    assert _exit_on_bar(o=100, h=116, l=99, stop=STOP, target=TGT) == ("target", TGT)


def test_exit_same_bar_tie_is_conservative_stop():
    # Bar spans both stop and target -> assume stop filled first.
    assert _exit_on_bar(o=100, h=116, l=94, stop=STOP, target=TGT) == ("stop", STOP)


def test_exit_none_when_untouched():
    assert _exit_on_bar(o=100, h=105, l=98, stop=STOP, target=TGT) == (None, None)


def test_same_bar_after_fill():
    assert _same_bar_after_fill(low=94, high=100, stop=STOP, target=TGT, fill=99) == ("stop", STOP)
    assert _same_bar_after_fill(low=99, high=116, stop=STOP, target=TGT, fill=99) == ("target", TGT)
    assert _same_bar_after_fill(low=99, high=100, stop=STOP, target=TGT, fill=99) == (None, None)


def _dates(n):
    import pandas as pd
    return pd.date_range("2026-01-01", periods=n, freq="D")


def test_close_computes_r_multiple_and_recovery():
    highs = np.array([100.0] * 20)
    lows = np.array([100.0] * 20)
    d = _dates(20)
    bt = {"max_hold_bars": 30}
    # target hit: entry 100, stop 95, exit 115 -> R = 15/5 = 3
    tr = _close(None, d, 2, 3, 8, entry=100, stop=95, target=115, exit_price=115,
                outcome="target", highs=highs, lows=lows, bt=bt)
    assert tr["r_multiple"] == 3.0 and tr["outcome"] == "target"

    # stop hit and price never recovered to target afterwards
    tr2 = _close(None, d, 2, 3, 8, entry=100, stop=95, target=115, exit_price=95,
                 outcome="stop", highs=highs, lows=lows, bt=bt)
    assert tr2["r_multiple"] == -1.0 and tr2["recovered"] is False

    # stop hit but a later bar reaches the target -> recovered
    highs2 = highs.copy(); highs2[10] = 120
    tr3 = _close(None, d, 2, 3, 8, entry=100, stop=95, target=115, exit_price=95,
                 outcome="stop", highs=highs2, lows=lows, bt=bt)
    assert tr3["recovered"] is True


def test_exit_on_bar_short_mirror():
    # short: target 85 < entry 100 < stop 115
    assert _exit_on_bar_short(o=118, h=120, l=117, stop=115, target=85) == ("stop", 118)   # gap up
    assert _exit_on_bar_short(o=80, h=82, l=78, stop=115, target=85) == ("target", 80)      # gap down
    assert _exit_on_bar_short(o=100, h=116, l=99, stop=115, target=85) == ("stop", 115)     # rose to stop
    assert _exit_on_bar_short(o=100, h=101, l=84, stop=115, target=85) == ("target", 85)    # fell to target
    assert _exit_on_bar_short(o=100, h=116, l=84, stop=115, target=85) == ("stop", 115)     # tie -> stop
    assert _exit_on_bar_short(o=100, h=105, l=95, stop=115, target=85) == (None, None)


def test_close_short_r_multiple():
    highs = np.array([100.0] * 20); lows = np.array([100.0] * 20)
    d = _dates(20); bt = {"max_hold_bars": 30}
    # short entry 100, stop 110, target 80. Target hit -> R = (100-80)/(110-100) = 2
    tr = _close(None, d, 2, 3, 8, entry=100, stop=110, target=80, exit_price=80,
                outcome="target", highs=highs, lows=lows, bt=bt, side="short")
    assert tr["r_multiple"] == 2.0 and tr["side"] == "short"
    # stop hit -> R = (100-110)/10 = -1
    tr2 = _close(None, d, 2, 3, 8, entry=100, stop=110, target=80, exit_price=110,
                 outcome="stop", highs=highs, lows=lows, bt=bt, side="short")
    assert tr2["r_multiple"] == -1.0


def test_summarize_stats():
    trades = [
        {"r_multiple": 3.0, "outcome": "target", "bars_held": 5, "recovered": False},
        {"r_multiple": -1.0, "outcome": "stop", "bars_held": 3, "recovered": True},
        {"r_multiple": -1.0, "outcome": "stop", "bars_held": 4, "recovered": False},
        {"r_multiple": 0.4, "outcome": "time", "bars_held": 30, "recovered": False},
    ]
    s = summarize(trades)
    assert s["n_trades"] == 4
    assert s["win_rate"] == 0.5                       # 2 of 4 have r > 0
    assert s["expectancy_r"] == round((3 - 1 - 1 + 0.4) / 4, 3)
    assert s["pct_stop"] == 0.5
    assert s["stopped_then_recovered"] == 0.5         # 1 of 2 stops recovered


def test_summarize_empty():
    assert summarize([])["n_trades"] == 0
