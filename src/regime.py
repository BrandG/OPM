"""Market-regime detection from a synthetic index of the universe.

The scanner is otherwise regime-blind — it will happily suggest dip-buys into a
market that is rolling over. This builds an equal-weight index from the universe's
daily returns and classifies each day as 'up' (index at/above its long moving
average) or 'down' (below it), so trades can be conditioned on the broad regime.

The synthetic index is itself survivorship-biased (built from current members, so
it drifts up), but the up/down-vs-its-own-trend classification still isolates the
pullback periods within the sample, which is what we need.
"""

from __future__ import annotations

import pandas as pd


def build_market_index(frames: dict) -> pd.Series:
    """Equal-weight, daily-rebalanced index from {symbol: OHLCV DataFrame}."""
    closes = pd.DataFrame({s: df["close"] for s, df in frames.items() if len(df)})
    daily_ret = closes.pct_change(fill_method=None)
    market_ret = daily_ret.mean(axis=1, skipna=True)     # avg across available names
    return (1 + market_ret.fillna(0)).cumprod()


def regime_series(index: pd.Series, period: int = 200) -> pd.Series:
    """Per-date 'up'/'down' from the index vs its `period`-day SMA.

    Warmup bars (before the SMA exists) are 'up' (neutral) — trades only start
    well after warmup, so this never mislabels a real signal.
    """
    ma = index.rolling(period).mean()
    reg = pd.Series("up", index=index.index)
    reg[index < ma] = "down"
    reg[ma.isna()] = "up"
    return reg


def regime_by_date(index: pd.Series, period: int = 200) -> dict:
    """Map ISO date string -> 'up'/'down' for tagging trades by signal date."""
    reg = regime_series(index, period)
    return {d.date().isoformat(): v for d, v in reg.items()}
