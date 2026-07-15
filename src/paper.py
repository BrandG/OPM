"""Forward paper-trade ledger — the walk-forward backtester, run live.

The backtester replays a full price history in one pass; this replays it **one
new bar at a time** as the daily cache grows, persisting each trade's state to
`paper_trades`. That single difference is the whole point: every fill and exit
here happens on data that did not exist when the strategy was frozen, so the
result is genuinely out-of-sample and free of survivorship bias (a name that
crashes out of the index still gets held to its stop, because we hold the row,
not the index membership).

The state machine and fill/exit rules are the SAME primitives the backtester
uses (`_ops`, `_exit_on_bar`, `apply_slippage`, `r_multiple`), so a paper trade
and a backtest trade over identical bars produce identical R. We do not re-derive
any trade logic here — we only persist and advance it.

Lifecycle per row:
    PENDING  -> fills when a bar dips to `entry` (gap-aware); cancels if unfilled
                within `entry_expiry_bars`.
    OPEN     -> exits on stop / target / `max_hold_bars` time stop.
    CLOSED / CANCELLED are terminal.

Gap-safety: each row stores `last_processed_date`. A run advances the row through
every cached bar strictly after that cursor, so a missed day (weekend, machine
off, systemd catch-up) is caught up correctly and re-running a day is a no-op.
"""

from __future__ import annotations

from typing import List, Optional

import pandas as pd

from src.backtest import _ops, apply_slippage, r_multiple


def _finalize(trade: dict, date: str, price: float, outcome: str, bt: dict) -> None:
    """Close a trade in place: apply the market-leg slippage haircut and book R."""
    exit_price = apply_slippage(price, outcome, trade["side"],
                                trade.get("sig_atr") or 0.0, bt.get("slippage_atr", 0.0))
    r, _planned = r_multiple(trade["side"], trade["entry"], trade["stop"],
                             trade["target"], exit_price)
    trade["status"] = "CLOSED"
    trade["exit_date"] = date
    trade["exit_price"] = round(exit_price, 4)
    trade["exit_reason"] = outcome
    trade["r_multiple"] = round(r, 3)


def advance_trade(trade: dict, df: pd.DataFrame, bt: dict) -> dict:
    """Advance one PENDING/OPEN trade through all cached bars after its cursor.

    Mutates and returns `trade`. `df` is the symbol's daily bars (read-only). No-op
    if there are no bars past the cursor. Stops at the bar that closes/cancels the
    trade (state is terminal thereafter).
    """
    if trade["status"] not in ("PENDING", "OPEN"):
        return trade
    ops = _ops(trade["side"])
    cursor = trade.get("last_processed_date") or trade["signal_date"]
    new_bars = df[df.index > pd.Timestamp(cursor)]

    for ts, bar in new_bars.iterrows():
        o, h, l, c = (float(bar["open"]), float(bar["high"]),
                      float(bar["low"]), float(bar["close"]))
        date = ts.date().isoformat()

        if trade["status"] == "PENDING":
            trade["bars_pending"] += 1
            if trade["bars_pending"] > bt["entry_expiry_bars"]:
                trade["status"] = "CANCELLED"
                trade["exit_date"] = date
                trade["exit_reason"] = "expired"
                trade["last_processed_date"] = date
                break
            if ops["fills"](l, h, trade["entry"]):
                fill = ops["fill_price"](o, trade["entry"])
                trade["status"] = "OPEN"
                trade["fill_date"] = date
                trade["fill_price"] = round(fill, 4)
                # Does the remainder of the fill bar already hit stop/target?
                outcome, price = ops["samebar"](l, h, trade["stop"], trade["target"], fill)
                if outcome:
                    _finalize(trade, date, price, outcome, bt)
                    trade["last_processed_date"] = date
                    break
            # else: still pending, roll to next bar

        elif trade["status"] == "OPEN":
            trade["bars_held"] += 1
            outcome, price = ops["exit"](o, h, l, trade["stop"], trade["target"])
            if not outcome and trade["bars_held"] >= bt["max_hold_bars"]:
                outcome, price = "time", c
            if outcome:
                _finalize(trade, date, price, outcome, bt)
                trade["last_processed_date"] = date
                break

        trade["last_processed_date"] = date

    return trade


def advance_all(store, frames: dict, bt: dict) -> List[dict]:
    """Advance every live paper trade and persist changes. Returns the trades that
    changed state this run (filled or closed), for the run summary."""
    changed = []
    for trade in store.get_open_paper_trades():
        df = frames.get(trade["symbol"])
        if df is None or df.empty:
            continue
        before = (trade["status"], trade.get("last_processed_date"))
        advance_trade(trade, df, bt)
        if (trade["status"], trade.get("last_processed_date")) == before:
            continue                      # no new bars -> nothing to write
        store.update_paper_trade(trade["id"], trade)
        if before[0] != trade["status"]:
            changed.append(trade)
    return changed


def record_setups(store, setups: List[dict], run_date: str, now: str) -> List[dict]:
    """Open a PENDING paper trade for each armed+passed setup we're not already in.

    Unconstrained by design: we record EVERY qualifying signal (one live position
    per symbol+side) so the ledger measures the signal's edge at full statistical
    N — the account-size cap is applied later as a reporting view, not here.
    """
    active = store.active_paper_keys()
    recorded = []
    for s in setups:
        if not (s.get("passed") and s.get("armed")):
            continue
        side = s.get("side", "long")
        key = (s["symbol"].upper(), side)
        if key in active:
            continue                      # already holding/pending this name+side
        rec = {
            "symbol": s["symbol"].upper(), "side": side, "status": "PENDING",
            "signal_date": run_date, "entry": s["entry"], "stop": s["stop"],
            "target": s["target"], "sig_atr": s.get("atr"),
            "planned_rr": s.get("rr"), "shares": s.get("shares"),
            "sector": s.get("sector", "?"), "trade_score": s.get("trade_score"),
            "corridor_pct": s.get("corridor_pct"),
            "bars_pending": 0, "bars_held": 0,
            "last_processed_date": run_date,   # entry becomes active on the NEXT bar
            "created_at": now, "updated_at": now,
        }
        rec["id"] = store.add_paper_trade(rec)
        recorded.append(rec)
        active.add(key)
    return recorded
