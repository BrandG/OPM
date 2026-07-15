"""Volatility ranking: ATR% on daily bars.

Ranks symbols by Average True Range as a fraction of price. True Range is
gap-inclusive (uses the prior close), which matters specifically here: the
account can't be watched intraday, so overnight gaps are real risk and a stock
that gaps but has a tight intraday range should still rank as volatile.

ATR uses Wilder's smoothing (the original definition), seeded by the simple
mean of the first `period` true ranges.
"""

from __future__ import annotations

from typing import List, Optional

import numpy as np
import pandas as pd


def true_range(df: pd.DataFrame) -> pd.Series:
    """Gap-inclusive True Range per bar.

    TR[0] falls back to high-low (no prior close). TR[i>=1] is the max of the
    current range and the gap-adjusted ranges against the prior close.
    """
    high, low, close = df["high"], df["low"], df["close"]
    prev_close = close.shift(1)
    hl = high - low
    hc = (high - prev_close).abs()
    lc = (low - prev_close).abs()
    tr = pd.concat([hl, hc, lc], axis=1).max(axis=1)
    tr.iloc[0] = (high.iloc[0] - low.iloc[0])  # no prior close for the first bar
    return tr


def wilder_atr(df: pd.DataFrame, period: int) -> pd.Series:
    """Wilder's ATR series. NaN until enough bars exist to seed it."""
    tr = true_range(df).to_numpy(dtype=float)
    n = len(tr)
    atr = np.full(n, np.nan)
    if n < period:
        return pd.Series(atr, index=df.index)
    atr[period - 1] = tr[:period].mean()
    for i in range(period, n):
        atr[i] = (atr[i - 1] * (period - 1) + tr[i]) / period
    return pd.Series(atr, index=df.index)


def atr_pct(df: pd.DataFrame, period: int) -> Optional[float]:
    """Latest ATR as a fraction of the latest close, or None if insufficient bars."""
    if len(df) < period:
        return None
    atr = wilder_atr(df, period).iloc[-1]
    close = df["close"].iloc[-1]
    if not np.isfinite(atr) or not close:
        return None
    return float(atr / close)


def rank_universe(
    store,
    symbols: List[str],
    period: int,
    top_n: Optional[int] = None,
    max_share_price: Optional[float] = None,
    min_bars: Optional[int] = None,
) -> pd.DataFrame:
    """Rank symbols by ATR% descending, reading bars from the store.

    Symbols with fewer than `min_bars` bars (default `period`; recent
    spinoffs/IPOs whose ATR% would be statistically unreliable), or (if
    `max_share_price` is set) a last close above the cap, are excluded. Returns
    a DataFrame with columns: symbol, last_close, atr, atr_pct, bars.
    """
    floor = max(period, min_bars) if min_bars else period
    rows = []
    for sym in symbols:
        df = store.get_bars(sym)
        if len(df) < floor:
            continue
        last_close = float(df["close"].iloc[-1])
        if max_share_price is not None and last_close > max_share_price:
            continue
        atr = float(wilder_atr(df, period).iloc[-1])
        rows.append(
            {
                "symbol": sym.upper(),
                "last_close": round(last_close, 2),
                "atr": round(atr, 2),
                "atr_pct": round(atr / last_close, 4),
                "bars": len(df),
            }
        )

    result = pd.DataFrame(rows, columns=["symbol", "last_close", "atr", "atr_pct", "bars"])
    result = result.sort_values("atr_pct", ascending=False, ignore_index=True)
    if top_n is not None:
        result = result.head(top_n)
    return result
