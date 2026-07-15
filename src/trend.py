"""Trend state for the trend filter.

A simple, look-ahead-free classification of a symbol's trend as of the latest
bar: 'up' if the close is above its long moving average (and the average is
rising), else 'down'. Used to gate longs to uptrends and shorts to downtrends.
"""

from __future__ import annotations

from typing import Optional


def sma(closes, period: int) -> Optional[float]:
    closes = list(closes)
    if len(closes) < period:
        return None
    return sum(closes[-period:]) / period


def trend_state(closes, period: int, slope_lookback: int = 20) -> str:
    """Return 'up' or 'down' from `closes` (uses only data up to the last bar).

    Defined by the SLOPE of the moving average: 'up' if the SMA is higher than it
    was `slope_lookback` bars ago, else 'down'. Deliberately NOT "close above the
    SMA" — a dip-buy strategy enters when price has pulled back below a moving
    average, so a position-based filter would remove the very dips it should keep.
    The slope filter instead removes falling-trend (knife-catch) names while
    leaving pullbacks within a rising trend intact. Insufficient history -> 'up'
    (neutral; the filter only ever removes trades).
    """
    closes = list(closes)
    now = sma(closes, period)
    prior = sma(closes[:-slope_lookback], period)
    if now is None or prior is None:
        return "up"
    return "up" if now >= prior else "down"
