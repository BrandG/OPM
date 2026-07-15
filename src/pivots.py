"""Fractal pivot detection on daily bars.

A pivot low is a bar whose low is strictly below the lows of the `n` bars on
each side; a pivot high is the mirror. This is the standard fractal definition,
and it bakes in the "bounce" requirement from the design spec for free — a
fractal low IS a local rejection, so every pivot is already a validated touch.

Note on confirmation lag: a pivot needs `n` bars on BOTH sides, so the most
recent `n` bars can never be confirmed as pivots yet. That is correct behavior
(you can't know a low held until price moves away from it), but it means live
scanning treats the last `n` bars as provisional.
"""

from __future__ import annotations

from typing import List

import pandas as pd


def find_pivots(df: pd.DataFrame, n: int) -> List[dict]:
    """Return fractal pivots as dicts: {idx, date, price, kind}.

    Args:
        df: daily bars indexed by date, with 'high'/'low' columns.
        n: fractal half-width (bars required on each side).

    kind is 'low' or 'high'. A single (outside) bar can qualify as both and is
    then emitted twice. Results are ordered by bar index (chronological).
    """
    lows = df["low"].to_numpy(dtype=float)
    highs = df["high"].to_numpy(dtype=float)
    dates = df.index
    out: List[dict] = []

    for i in range(n, len(df) - n):
        lo = lows[i]
        if all(lo < lows[i - k] for k in range(1, n + 1)) and all(
            lo < lows[i + k] for k in range(1, n + 1)
        ):
            out.append({"idx": i, "date": dates[i], "price": float(lo), "kind": "low"})

        hi = highs[i]
        if all(hi > highs[i - k] for k in range(1, n + 1)) and all(
            hi > highs[i + k] for k in range(1, n + 1)
        ):
            out.append({"idx": i, "date": dates[i], "price": float(hi), "kind": "high"})

    return out
