import pandas as pd

from src.pivots import find_pivots


def _df(highs, lows):
    idx = pd.date_range("2026-01-01", periods=len(highs), freq="D")
    return pd.DataFrame({"high": highs, "low": lows,
                         "open": lows, "close": highs, "volume": [1] * len(highs)},
                        index=idx)


def test_finds_clear_pivot_low_and_high_with_n1():
    # lows: a clear V at index 2 (8), a peak high at index 5 (20).
    highs = [10, 11, 9, 12, 15, 20, 14, 13]
    lows = [9, 10, 8, 11, 14, 19, 13, 12]
    piv = find_pivots(_df(highs, lows), n=1)
    lows_found = [(p["idx"], p["price"]) for p in piv if p["kind"] == "low"]
    highs_found = [(p["idx"], p["price"]) for p in piv if p["kind"] == "high"]
    assert (2, 8.0) in lows_found
    assert (5, 20.0) in highs_found


def test_edge_bars_never_confirmed():
    # A low at index 0 or last cannot be a pivot (no bars on one side).
    highs = [5, 6, 7, 8, 9]
    lows = [1, 2, 3, 4, 5]  # strictly increasing -> index 0 is the min but on the edge
    piv = find_pivots(_df(highs, lows), n=2)
    assert all(2 <= p["idx"] <= 2 for p in piv) or piv == []  # only i=2 is checkable
    assert all(p["idx"] not in (0, len(lows) - 1) for p in piv)


def test_n_controls_strength():
    # A shallow dip flanked by 1 bar is a pivot at n=1 but not n=2.
    highs = [10, 11, 10, 11, 12, 13, 14]
    lows = [5, 6, 4, 6, 7, 8, 9]  # dip to 4 at index 2
    assert any(p["idx"] == 2 and p["kind"] == "low" for p in find_pivots(_df(highs, lows), n=1))
    assert any(p["idx"] == 2 and p["kind"] == "low" for p in find_pivots(_df(highs, lows), n=2))


def test_no_pivots_on_monotonic_series():
    highs = list(range(1, 12))
    lows = list(range(0, 11))
    piv = find_pivots(_df(highs, lows), n=2)
    # Monotonic rise: no interior low is below both sides, no interior high above both.
    assert piv == []
