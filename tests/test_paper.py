"""Forward paper-ledger engine tests.

The ledger reuses the backtester's fill/exit primitives, so beyond the state
machine we lock the invariant that a paper close prices exactly like a backtest
close (same slippage, same R) — that's what makes forward numbers comparable to
the backtest bar.
"""

import numpy as np
import pandas as pd

from src.backtest import _close
from src.paper import advance_trade, record_setups, advance_all, _finalize
from src.storage import Store


BT = {"entry_expiry_bars": 10, "max_hold_bars": 30, "slippage_atr": 0.0}


def _df(rows):
    """rows: list of (date, open, high, low, close)."""
    idx = pd.to_datetime([r[0] for r in rows])
    return pd.DataFrame(
        {"open": [r[1] for r in rows], "high": [r[2] for r in rows],
         "low": [r[3] for r in rows], "close": [r[4] for r in rows]}, index=idx)


def _pending(**kw):
    base = {"id": 1, "symbol": "TST", "side": "long", "status": "PENDING",
            "signal_date": "2026-01-01", "entry": 100.0, "stop": 95.0,
            "target": 115.0, "sig_atr": 10.0, "bars_pending": 0, "bars_held": 0,
            "last_processed_date": "2026-01-01"}
    base.update(kw)
    return base


def test_fill_then_target():
    df = _df([
        ("2026-01-01", 101, 102, 100.5, 101),   # signal day (ignored: not > cursor)
        ("2026-01-02", 101, 105, 99, 104),       # dips to 100 -> fill at 100
        ("2026-01-03", 105, 116, 104, 115),      # tags target 115
    ])
    t = advance_trade(_pending(), df, BT)
    assert t["status"] == "CLOSED"
    assert t["fill_price"] == 100.0
    assert t["exit_reason"] == "target"
    assert t["r_multiple"] == 3.0            # (115-100)/(100-95)


def test_fill_then_stop():
    df = _df([
        ("2026-01-02", 101, 103, 99, 102),       # fill 100
        ("2026-01-03", 100, 101, 94, 96),        # low 94 -> stop 95
    ])
    t = advance_trade(_pending(), df, BT)
    assert t["status"] == "CLOSED"
    assert t["exit_reason"] == "stop"
    assert t["r_multiple"] == -1.0


def test_entry_expiry_cancels():
    # 11 bars all above entry -> never fills, cancels after entry_expiry_bars=10.
    rows = [(f"2026-02-{d:02d}", 110, 112, 108, 111) for d in range(2, 14)]
    t = advance_trade(_pending(), _df(rows), BT)
    assert t["status"] == "CANCELLED"
    assert t["exit_reason"] == "expired"
    assert t["bars_pending"] == 11           # tripped one past the 10-bar window


def test_time_stop():
    bt = {**BT, "max_hold_bars": 3}
    rows = [("2026-03-02", 101, 103, 99, 102)]          # fill 100
    rows += [(f"2026-03-{d:02d}", 101, 104, 99.5, 102)  # never hits 95 or 115
             for d in range(3, 8)]
    t = advance_trade(_pending(), _df(rows), bt)
    assert t["status"] == "CLOSED"
    assert t["exit_reason"] == "time"
    assert t["bars_held"] == 3


def test_gap_safe_and_idempotent():
    df = _df([
        ("2026-01-02", 101, 105, 99, 104),   # fill
        ("2026-01-03", 105, 108, 104, 106),  # open, no exit
    ])
    t = _pending()
    advance_trade(t, df, BT)
    assert t["status"] == "OPEN" and t["last_processed_date"] == "2026-01-03"
    # Re-run with the same frame: no bars past the cursor -> nothing changes.
    snapshot = dict(t)
    advance_trade(t, df, BT)
    assert t == snapshot


def test_slippage_matches_backtest_close():
    """A paper stop exit must price identically to a backtest stop exit."""
    bt = {"slippage_atr": 0.05, "max_hold_bars": 30, "entry_expiry_bars": 10}
    flat = np.array([100.0] * 5)
    bt_close = _close(None, pd.to_datetime(["2026-01-0%d" % i for i in range(1, 6)]),
                      0, 1, 3, entry=100, stop=95, target=115, exit_price=95,
                      outcome="stop", highs=flat, lows=flat, bt=bt, side="long",
                      sig_atr=10.0)
    tr = _pending(status="OPEN")
    _finalize(tr, "2026-01-05", 95.0, "stop", bt)
    assert tr["r_multiple"] == bt_close["r_multiple"]   # 95 - 0.5 slip -> -1.1R
    assert tr["r_multiple"] == -1.1


def test_record_dedups_active_symbol(tmp_path):
    store = Store(tmp_path / "p.db")
    setup = {"symbol": "AMD", "side": "long", "passed": True, "armed": True,
             "entry": 100, "stop": 95, "target": 115, "atr": 10, "rr": 3.0,
             "shares": 1.5, "sector": "Tech", "trade_score": 80, "corridor_pct": 0.1}
    rec = record_setups(store, [setup], "2026-01-01", "now")
    assert len(rec) == 1
    # Same armed name again while still pending -> skipped.
    rec2 = record_setups(store, [setup], "2026-01-02", "now")
    assert rec2 == []
    assert len(store.all_paper_trades()) == 1


def test_record_skips_unarmed(tmp_path):
    store = Store(tmp_path / "p.db")
    setups = [
        {"symbol": "A", "passed": True, "armed": False, "entry": 1, "stop": 0.9,
         "target": 1.3, "atr": 0.1},
        {"symbol": "B", "passed": False, "armed": True, "entry": 1, "stop": 0.9,
         "target": 1.3, "atr": 0.1},
    ]
    assert record_setups(store, setups, "2026-01-01", "now") == []


def test_advance_all_persists(tmp_path):
    store = Store(tmp_path / "p.db")
    store.add_paper_trade(_pending())
    frames = {"TST": _df([
        ("2026-01-02", 101, 105, 99, 104),   # fill 100
        ("2026-01-03", 105, 116, 104, 115),  # target
    ])}
    changed = advance_all(store, frames, BT)
    assert len(changed) == 1
    reloaded = store.all_paper_trades("CLOSED")
    assert len(reloaded) == 1
    assert reloaded[0]["r_multiple"] == 3.0
