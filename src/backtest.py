"""Walk-forward backtester for the bracket setups.

The one rule that matters: **no look-ahead**. At each bar i we rebuild zones from
`df.iloc[:i+1]` only (detect_zones then trims to its trailing lookback), generate
the setup at close[i], and place a buy-limit entry that becomes active on i+1.
Nothing about the trade decision can see a future bar.

Trade lifecycle (per symbol, one position at a time):
  FLAT     -> re-detect every `resignal_every` bars; if a setup passes & is armed,
              arm a pending buy-limit at `entry` (active next bar).
  PENDING  -> fills when a later bar's low <= entry (fill = min(open, entry) to
              respect gap-downs). Cancels if unfilled within `entry_expiry_bars`.
  IN_TRADE -> exits on stop, target, or a `max_hold_bars` time stop. Gaps are
              honoured at the open; if a single bar spans both stop and target we
              assume the stop filled first (conservative).

Edge is reported in R-multiples: (exit - entry) / (entry - stop). A target hit is
about +planned_rr; a stop is about -1. This isolates the setup's edge from
position sizing. `recovered` flags stopped trades whose target was reached within
the hold window anyway — the "stopped out by noise" rate that tunes stop_atr_buffer.
"""

from __future__ import annotations

from statistics import mean
from typing import List, Optional

import pandas as pd

from src.zones import detect_zones
from src.scoring import score_zones
from src.trades import build_setup, build_short_setup
from src.trend import trend_state


def _exit_on_bar(o: float, h: float, l: float, stop: float, target: float):
    """LONG exit for a bar in a trade (stop < entry < target). Returns
    (outcome, price) or (None, None). Gaps honoured at open; stop wins ties."""
    if o <= stop:
        return "stop", o                # gapped down through the stop
    if o >= target:
        return "target", o              # gapped up through the target
    hit_stop, hit_tgt = l <= stop, h >= target
    if hit_stop:
        return "stop", stop             # conservative on same-bar stop+target
    if hit_tgt:
        return "target", target
    return None, None


def _exit_on_bar_short(o: float, h: float, l: float, stop: float, target: float):
    """SHORT exit (target < entry < stop). Mirror of _exit_on_bar."""
    if o >= stop:
        return "stop", o                # gapped up through the stop
    if o <= target:
        return "target", o              # gapped down through the target
    hit_stop, hit_tgt = h >= stop, l <= target
    if hit_stop:
        return "stop", stop             # conservative on same-bar tie
    if hit_tgt:
        return "target", target
    return None, None


def _same_bar_after_fill_short(low, high, stop, target, fill):
    if high >= stop:
        return "stop", stop
    if low <= target:
        return "target", target
    return None, None


# Per-side operations so the simulation loop stays single-sourced.
def _ops(side: str) -> dict:
    if side == "short":
        return {
            "build": build_short_setup,
            "fills": lambda low, high, entry: high >= entry,   # rallies up to short-limit
            "fill_price": lambda o, entry: max(o, entry),
            "exit": _exit_on_bar_short,
            "samebar": _same_bar_after_fill_short,
        }
    return {
        "build": build_setup,
        "fills": lambda low, high, entry: low <= entry,        # dips to buy-limit
        "fill_price": lambda o, entry: min(o, entry),
        "exit": _exit_on_bar,
        "samebar": _same_bar_after_fill,
    }


def simulate_symbol(df: pd.DataFrame, dp: dict, t: dict, bt: dict,
                    weights: dict, params: dict, side: str = "long") -> List[dict]:
    """Walk-forward simulation for one symbol and one side; return closed trades."""
    trades: List[dict] = []
    n = len(df)
    warmup = bt["warmup_bars"]
    if n <= warmup + 2:
        return trades

    ops = _ops(side)
    closes = df["close"].to_numpy()
    opens = df["open"].to_numpy()
    highs = df["high"].to_numpy()
    lows = df["low"].to_numpy()
    dates = df.index

    state = "FLAT"
    last_detect = -10_000
    entry = stop = target = sig_atr = sig_score = 0.0
    signal_i = entry_i = 0
    fill = 0.0

    i = warmup
    while i < n:
        if state == "PENDING":
            if i - signal_i > bt["entry_expiry_bars"]:
                state = "FLAT"                       # entry limit expired unfilled
            elif ops["fills"](lows[i], highs[i], entry):
                fill = ops["fill_price"](opens[i], entry)
                entry_i = i
                outcome, price = ops["samebar"](lows[i], highs[i], stop, target, fill)
                if outcome:
                    trades.append(_close(df, dates, signal_i, entry_i, i, fill, stop,
                                         target, price, outcome, highs, lows, bt, side, sig_atr, sig_score))
                    state = "FLAT"
                else:
                    state = "IN_TRADE"

        elif state == "IN_TRADE":
            held = i - entry_i
            outcome, price = ops["exit"](opens[i], highs[i], lows[i], stop, target)
            if not outcome and held >= bt["max_hold_bars"]:
                outcome, price = "time", closes[i]
            if outcome:
                trades.append(_close(df, dates, signal_i, entry_i, i, fill, stop,
                                     target, price, outcome, highs, lows, bt, side, sig_atr, sig_score))
                state = "FLAT"

        if state == "FLAT" and i - last_detect >= bt["resignal_every"]:
            last_detect = i
            hist = df.iloc[: i + 1]
            res = detect_zones(hist, **dp)
            scored = score_zones(res["zones"], res["df"], res["atr"], weights,
                                 params, atr_pct=res["atr_pct"])
            trend = trend_state(closes[: i + 1], t["trend_sma_period"]) \
                if t.get("require_trend") else None
            setup = ops["build"](df.index.name or "SYM", scored, float(closes[i]),
                                 res["atr"], t, closes=res["df"]["close"].to_numpy(),
                                 trend=trend)
            if setup["passed"] and setup["armed"]:
                entry, stop, target = setup["entry"], setup["stop"], setup["target"]
                sig_atr = res["atr"]
                sig_score = setup["trade_score"]
                signal_i = i
                state = "PENDING"
        i += 1

    return trades


def _same_bar_after_fill(low, high, stop, target, fill):
    """After a mid-bar fill, does the remainder of the bar hit stop/target?"""
    hit_stop, hit_tgt = low <= stop, high >= target
    if hit_stop:
        return "stop", stop
    if hit_tgt:
        return "target", target
    return None, None


def apply_slippage(exit_price: float, outcome: str, side: str, sig_atr: float,
                   slippage_atr: float) -> float:
    """Adverse fill on the market-order legs only. Stop and time exits are market
    orders and take `slippage_atr * ATR` of slippage; limit entry and limit target
    fill at price-or-better, so they're untouched. Shared by the backtester and the
    forward paper ledger so both price exits identically."""
    slip = slippage_atr * sig_atr
    if slip and outcome in ("stop", "time"):
        return exit_price - slip if side == "long" else exit_price + slip
    return exit_price


def r_multiple(side: str, entry: float, stop: float, target: float,
               exit_price: float):
    """(realized_R, planned_RR) for a closed trade. R = reward per unit of risk,
    where risk = |entry - stop|. Single-sourced so backtest and paper agree."""
    if side == "short":
        risk = stop - entry
        r = (entry - exit_price) / risk if risk > 0 else 0.0
        planned = round((entry - target) / risk, 2) if risk > 0 else 0.0
    else:
        risk = entry - stop
        r = (exit_price - entry) / risk if risk > 0 else 0.0
        planned = round((target - entry) / risk, 2) if risk > 0 else 0.0
    return r, planned


def _close(df, dates, signal_i, entry_i, exit_i, entry, stop, target, exit_price,
           outcome, highs, lows, bt, side="long", sig_atr=0.0, sig_score=0.0) -> dict:
    exit_price = apply_slippage(exit_price, outcome, side, sig_atr,
                                bt.get("slippage_atr", 0.0))
    r, planned = r_multiple(side, entry, stop, target, exit_price)
    # "stopped by noise": would the target have been reached within the hold window?
    recovered = False
    if outcome == "stop":
        end = min(len(highs), entry_i + int(bt["max_hold_bars"]) + 1)
        future = (lows[exit_i + 1: end] <= target) if side == "short" \
            else (highs[exit_i + 1: end] >= target)
        recovered = bool(future.any())
    return {
        "side": side,
        "signal_date": dates[signal_i].date().isoformat(),
        "entry_date": dates[entry_i].date().isoformat(),
        "exit_date": dates[exit_i].date().isoformat(),
        "entry": round(entry, 2), "stop": round(stop, 2), "target": round(target, 2),
        "exit": round(exit_price, 2), "outcome": outcome,
        "bars_held": exit_i - entry_i, "r_multiple": round(r, 3),
        "planned_rr": planned, "recovered": recovered,
        "trade_score": round(sig_score, 1),
    }


def summarize(trades: List[dict]) -> dict:
    """Aggregate per-trade R-multiples into edge statistics."""
    if not trades:
        return {"n_trades": 0}
    rs = [t["r_multiple"] for t in trades]
    wins = [r for r in rs if r > 0]
    losses = [r for r in rs if r <= 0]
    stops = [t for t in trades if t["outcome"] == "stop"]
    recovered = [t for t in stops if t["recovered"]]
    gross_win = sum(wins)
    gross_loss = -sum(losses)
    return {
        "n_trades": len(trades),
        "win_rate": round(len(wins) / len(trades), 3),
        "expectancy_r": round(mean(rs), 3),          # avg R per trade (the headline)
        "avg_win_r": round(mean(wins), 3) if wins else 0.0,
        "avg_loss_r": round(mean(losses), 3) if losses else 0.0,
        "profit_factor": round(gross_win / gross_loss, 2) if gross_loss else float("inf"),
        "total_r": round(sum(rs), 1),
        "pct_target": round(sum(1 for t in trades if t["outcome"] == "target") / len(trades), 3),
        "pct_stop": round(len(stops) / len(trades), 3),
        "pct_time": round(sum(1 for t in trades if t["outcome"] == "time") / len(trades), 3),
        "stopped_then_recovered": round(len(recovered) / len(stops), 3) if stops else 0.0,
        "avg_bars_held": round(mean(t["bars_held"] for t in trades), 1),
    }
