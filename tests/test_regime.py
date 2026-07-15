import numpy as np
import pandas as pd

from src.regime import build_market_index, regime_series


def _frame(closes):
    idx = pd.date_range("2024-01-01", periods=len(closes), freq="D")
    return pd.DataFrame({"open": closes, "high": closes, "low": closes,
                         "close": closes, "volume": [1] * len(closes)}, index=idx)


def test_index_tracks_average_move():
    # Two names, one flat, one doubling -> index rises.
    frames = {"A": _frame([100] * 300), "B": _frame(list(np.linspace(100, 200, 300)))}
    idx = build_market_index(frames)
    assert idx.iloc[-1] > idx.iloc[0]


def test_regime_flips_up_then_down():
    up = list(np.linspace(100, 200, 250))       # rising
    down = list(np.linspace(200, 120, 120))      # then falling
    frames = {"X": _frame(up + down)}
    idx = build_market_index(frames)
    reg = regime_series(idx, period=100)
    assert reg.iloc[200] == "up"                 # during the rise
    assert reg.iloc[-1] == "down"                # deep into the fall
