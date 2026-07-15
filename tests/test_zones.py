import pandas as pd

from src.zones import cluster_pivots, detect_zones


def _piv(price, kind, day):
    return {"idx": day, "date": pd.Timestamp("2026-01-01") + pd.Timedelta(days=day),
            "price": price, "kind": kind}


def test_clusters_within_tolerance_and_splits_beyond():
    # tol_frac=0.05 (5%). Group A near 100 (within 2%), Group B near 130.
    pivots = [_piv(100, "low", 1), _piv(102, "low", 5), _piv(101, "low", 9),
              _piv(130, "high", 3), _piv(131, "high", 7)]
    zones = cluster_pivots(pivots, tol_frac=0.05, atr=10, min_touches=1)
    assert len(zones) == 2
    a, b = zones  # sorted by center ascending
    assert a["touches"] == 3 and a["kind"] == "support"
    assert round(a["low"], 1) == 100 and round(a["high"], 1) == 102
    assert b["touches"] == 2 and b["kind"] == "resistance"


def test_anchored_width_prevents_chain_drift():
    # Evenly spaced by 3 (each gap ~3% < tol) but total span 9 is larger.
    # Anchored merge must NOT swallow all into one wide zone; each zone's width
    # stays within tol_frac of its low member.
    pivots = [_piv(100, "low", 1), _piv(103, "low", 2), _piv(106, "low", 3),
              _piv(109, "low", 4)]
    zones = cluster_pivots(pivots, tol_frac=0.035, atr=10, min_touches=1)
    assert len(zones) > 1
    assert all(z["width"] <= 0.035 * z["low"] + 1e-9 for z in zones)


def test_price_relative_tolerance_scales_with_level():
    # Same 3-unit gap: merges at $100 (3%) but splits at $30 (10%) for tol=5%.
    hi = cluster_pivots([_piv(100, "low", 1), _piv(103, "low", 2)],
                        tol_frac=0.05, atr=5, min_touches=1)
    lo = cluster_pivots([_piv(30, "low", 1), _piv(33, "low", 2)],
                        tol_frac=0.05, atr=5, min_touches=1)
    assert len(hi) == 1 and len(lo) == 2


def test_mixed_zone_when_low_and_high_tie():
    pivots = [_piv(50, "low", 1), _piv(51, "high", 2)]
    zones = cluster_pivots(pivots, tol_frac=0.05, atr=10, min_touches=1)
    assert len(zones) == 1
    assert zones[0]["kind"] == "mixed"


def test_min_touches_filter():
    pivots = [_piv(50, "low", 1), _piv(80, "high", 2)]  # two isolated single-touch zones
    assert cluster_pivots(pivots, tol_frac=0.03, atr=5, min_touches=2) == []


def test_detect_zones_end_to_end():
    # Build bars with two repeated support touches near 90 and resistance near 110.
    lows = [95, 90, 96, 97, 98, 99, 100, 91, 97, 98, 99, 100, 101]
    highs = [105, 106, 107, 108, 109, 110, 104, 106, 107, 108, 109, 110, 104]
    idx = pd.date_range("2026-01-01", periods=len(lows), freq="D")
    df = pd.DataFrame({"low": lows, "high": highs, "open": lows, "close": highs,
                       "volume": [1] * len(lows)}, index=idx)
    res = detect_zones(df, n=1, atr_period=5, tolerance=0.5, min_touches=1)
    assert res["atr"] > 0
    assert len(res["zones"]) >= 1
