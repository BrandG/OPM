"""Normalize IBKR get_price_history responses into daily bar rows.

The API returns parallel columnar arrays (time/open/high/low/close/volume).
This module converts that into a list of validated per-bar dicts keyed by
session date, ready for storage. Kept pure (no I/O) for easy testing.
"""

from __future__ import annotations

from typing import List, Optional


class PriceHistoryError(ValueError):
    """Raised when a get_price_history payload is malformed."""


def _session_date(iso_ts: str) -> str:
    """Extract the YYYY-MM-DD session date from an ISO timestamp.

    Bars are stamped at the market open (e.g. '2025-07-08T13:30:00Z', shifting
    to 14:30Z across the US DST boundary). Both map to the same calendar date,
    which is all we need for daily bars.
    """
    return iso_ts.split("T", 1)[0]


def normalize_price_history(raw: dict, symbol: str) -> List[dict]:
    """Convert a get_price_history payload into daily bar rows.

    Args:
        raw: the raw JSON dict from get_price_history.
        symbol: the ticker this payload belongs to.

    Returns:
        A list of dicts: {symbol, date, open, high, low, close, volume},
        sorted ascending by date, with any bar missing a close dropped.

    Raises:
        PriceHistoryError: if required arrays are absent or length-mismatched.
    """
    required = ("time", "open", "high", "low", "close", "volume")
    for key in required:
        if key not in raw:
            raise PriceHistoryError(f"missing '{key}' array in price history payload")

    cols = {k: raw[k] for k in required}
    n = len(cols["time"])
    for key, arr in cols.items():
        if len(arr) != n:
            raise PriceHistoryError(
                f"array length mismatch: 'time' has {n}, '{key}' has {len(arr)}"
            )

    rows: List[dict] = []
    for i in range(n):
        close = cols["close"][i]
        if close is None:
            continue  # a bar with no close is unusable for level detection
        rows.append(
            {
                "symbol": symbol.upper(),
                "date": _session_date(cols["time"][i]),
                "open": _num(cols["open"][i]),
                "high": _num(cols["high"][i]),
                "low": _num(cols["low"][i]),
                "close": _num(close),
                "volume": _int(cols["volume"][i]),
            }
        )

    rows.sort(key=lambda r: r["date"])
    return rows


def _num(v) -> Optional[float]:
    return None if v is None else float(v)


def _int(v) -> Optional[int]:
    return None if v is None else int(v)
