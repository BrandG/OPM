import numpy as np
import pandas as pd

from src.volatility import true_range, wilder_atr, atr_pct, rank_universe
from src.storage import Store


def _df(bars):
    """bars: list of (high, low, close) — open/volume filled in, dates synthesized."""
    idx = pd.date_range("2026-01-01", periods=len(bars), freq="D")
    return pd.DataFrame(
        {
            "open": [b[2] for b in bars],
            "high": [b[0] for b in bars],
            "low": [b[1] for b in bars],
            "close": [b[2] for b in bars],
            "volume": [1000] * len(bars),
        },
        index=idx,
    )


# Hand-computed reference case, period=3:
#   TR = [2, 2, 2, 2, 1]
#   ATR[2]=mean(2,2,2)=2 ; ATR[3]=(2*2+2)/3=2 ; ATR[4]=(2*2+1)/3=5/3
BARS = [(10, 8, 9), (11, 9, 10), (12, 10, 11), (11, 9, 9.5), (10.5, 9.5, 10)]


def test_true_range_gap_inclusive():
    tr = true_range(_df(BARS))
    assert list(np.round(tr.to_numpy(), 4)) == [2.0, 2.0, 2.0, 2.0, 1.0]


def test_wilder_atr_matches_hand_computation():
    atr = wilder_atr(_df(BARS), period=3)
    assert np.isnan(atr.iloc[0]) and np.isnan(atr.iloc[1])
    assert round(atr.iloc[2], 4) == 2.0
    assert round(atr.iloc[3], 4) == 2.0
    assert round(atr.iloc[4], 4) == round(5 / 3, 4)


def test_atr_pct_uses_latest_close():
    assert round(atr_pct(_df(BARS), period=3), 4) == round((5 / 3) / 10, 4)


def test_atr_pct_insufficient_bars_returns_none():
    assert atr_pct(_df(BARS[:2]), period=3) is None


def test_rank_universe_orders_by_atr_pct(tmp_path):
    store = Store(tmp_path / "t.db")

    # LOWVOL: tight 1-wide ranges around ~100 -> low ATR%.
    low = [(100, 99, 99.5)] * 6
    # HIGHVOL: 10-wide ranges around ~50 -> high ATR%.
    high = [(55, 45, 50)] * 6

    for sym, bars in [("LOWVOL", low), ("HIGHVOL", high)]:
        df = _df(bars)
        store.upsert_bars([
            {"symbol": sym, "date": d.strftime("%Y-%m-%d"),
             "open": r.open, "high": r.high, "low": r.low, "close": r.close, "volume": 1000}
            for d, r in df.iterrows()
        ])

    ranked = rank_universe(store, ["LOWVOL", "HIGHVOL"], period=3)
    assert list(ranked["symbol"]) == ["HIGHVOL", "LOWVOL"]
    assert ranked["atr_pct"].iloc[0] > ranked["atr_pct"].iloc[1]


def test_rank_universe_max_price_filter(tmp_path):
    store = Store(tmp_path / "t.db")
    for sym, price in [("CHEAP", 50.0), ("PRICEY", 500.0)]:
        bars = [(price * 1.05, price * 0.95, price)] * 6
        df = _df(bars)
        store.upsert_bars([
            {"symbol": sym, "date": d.strftime("%Y-%m-%d"),
             "open": r.open, "high": r.high, "low": r.low, "close": r.close, "volume": 1000}
            for d, r in df.iterrows()
        ])

    ranked = rank_universe(store, ["CHEAP", "PRICEY"], period=3, max_share_price=100)
    assert list(ranked["symbol"]) == ["CHEAP"]


def test_rank_universe_min_bars_excludes_thin_history(tmp_path):
    store = Store(tmp_path / "t.db")
    # ESTAB has 10 bars; FRESH has only 4 — both exceed period=3.
    for sym, n in [("ESTAB", 10), ("FRESH", 4)]:
        bars = [(52, 48, 50)] * n
        df = _df(bars)
        store.upsert_bars([
            {"symbol": sym, "date": d.strftime("%Y-%m-%d"),
             "open": r.open, "high": r.high, "low": r.low, "close": r.close, "volume": 1000}
            for d, r in df.iterrows()
        ])
    # With min_bars=8, the 4-bar name is filtered even though it clears period.
    ranked = rank_universe(store, ["ESTAB", "FRESH"], period=3, min_bars=8)
    assert list(ranked["symbol"]) == ["ESTAB"]
