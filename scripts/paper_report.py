"""Forward paper-ledger scorecard: is the live edge tracking the backtest?

Two views of the same ledger, answering two different questions:

  UNCONSTRAINED (R-multiples, every recorded signal) — "does the signal have
    forward edge?" Full statistical N, sizing-independent. Compare its
    expectancy directly against the honest backtest bar (~+0.12–0.18R net).

  CONSTRAINED (dollars, capped at the account's concurrent-position limit) —
    "what would my actual account have made?" Walks fills chronologically and
    only takes a trade if a position slot is free, using the sized shares. This
    is the portfolio simulation the per-trade backtest never did.

Usage:
    python scripts/paper_report.py [--config config.yaml]
"""

import argparse
import sys
from math import floor
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.storage import Store
from src.backtest import summarize


def _r_view(closed: list) -> list:
    """Map paper rows onto the shape backtest.summarize expects."""
    return [{"r_multiple": t["r_multiple"], "outcome": t["exit_reason"],
             "bars_held": t.get("bars_held") or 0, "recovered": False}
            for t in closed if t.get("r_multiple") is not None]


def _constrained_pnl(filled: list, max_slots: int) -> dict:
    """Chronological portfolio sim: at most `max_slots` positions at once. A signal
    that fires while all slots are full is skipped (as it would be live)."""
    # Order by fill date; a trade occupies a slot from fill_date to exit_date.
    filled = sorted(filled, key=lambda t: (t["fill_date"], t["id"]))
    open_slots = []          # list of exit_date strings currently occupying a slot
    taken, skipped, pnl = [], 0, 0.0
    for t in filled:
        open_slots = [d for d in open_slots if d is None or d > t["fill_date"]]
        if len(open_slots) >= max_slots:
            skipped += 1
            continue
        open_slots.append(t.get("exit_date"))     # None = still open, holds a slot
        shares = t.get("shares") or 0.0
        if t.get("exit_price") is not None:
            gain = (t["exit_price"] - t["entry"]) if t["side"] == "long" \
                else (t["entry"] - t["exit_price"])
            pnl += shares * gain
        taken.append(t)
    return {"taken": len(taken), "skipped": skipped, "realized_pnl": round(pnl, 2)}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config.yaml")
    args = ap.parse_args()
    cfg = yaml.safe_load(Path(args.config).read_text())
    t = cfg["trade"]
    store = Store(cfg["data"]["db_path"])

    all_trades = store.all_paper_trades()
    if not all_trades:
        print("No paper trades recorded yet. Run scripts/paper_advance.py "
              "(or run_cycle.sh) after the next close.")
        return

    by_status = lambda s: [x for x in all_trades if x["status"] == s]
    pending, open_, closed, cancelled = (by_status("PENDING"), by_status("OPEN"),
                                         by_status("CLOSED"), by_status("CANCELLED"))
    exited = [c for c in closed if c["exit_reason"] != "expired"]

    print("=" * 66)
    print("OPM FORWARD PAPER LEDGER")
    print("=" * 66)
    print(f"recorded {len(all_trades)} signals  ·  {len(pending)} pending  "
          f"{len(open_)} open  {len(closed)} closed  {len(cancelled)} cancelled\n")

    # --- unconstrained R edge (the validation number) ---
    stats = summarize(_r_view(exited))
    if stats.get("n_trades"):
        print("UNCONSTRAINED signal edge (all recorded, R-multiples):")
        print(f"  n={stats['n_trades']}  expectancy {stats['expectancy_r']:+.3f}R  "
              f"PF {stats['profit_factor']}  win {stats['win_rate']:.0%}  "
              f"total {stats['total_r']:+.1f}R")
        print(f"  targets {stats['pct_target']:.0%} · stops {stats['pct_stop']:.0%} · "
              f"time {stats['pct_time']:.0%} · avg hold {stats['avg_bars_held']} bars")
        print(f"  vs backtest honest bar ~+0.12–0.18R net "
              f"({'TRACKING' if stats['expectancy_r'] >= 0.12 else 'BELOW — watch'})\n")
    else:
        print("UNCONSTRAINED: no closed trades yet (need fills to exit first).\n")

    # --- constrained account P&L (what the real book would hold) ---
    max_slots = floor(1 / t["max_position_pct"]) if t["max_position_pct"] else 0
    filled = [x for x in (open_ + closed) if x.get("fill_date")]
    if filled and max_slots:
        pc = _constrained_pnl([x for x in filled if x.get("exit_date")], max_slots)
        equity = t["account_equity"]
        print(f"CONSTRAINED account view (<= {max_slots} concurrent positions, "
              f"sized shares):")
        print(f"  took {pc['taken']} / skipped {pc['skipped']} (no free slot)  ·  "
              f"realized P&L ${pc['realized_pnl']:+,.2f} "
              f"({pc['realized_pnl']/equity:+.1%} on ${equity:,.0f})\n")

    # --- open book ---
    live = pending + open_
    if live:
        print("OPEN BOOK:")
        for x in sorted(live, key=lambda r: (r["status"], r["symbol"])):
            if x["status"] == "PENDING":
                print(f"  {x['symbol']:<6} PENDING  entry {x['entry']:.2f}  "
                      f"stop {x['stop']:.2f}  tgt {x['target']:.2f}  "
                      f"(waited {x['bars_pending']}b, signaled {x['signal_date']})")
            else:
                print(f"  {x['symbol']:<6} OPEN     filled {x['fill_price']:.2f} "
                      f"@ {x['fill_date']}  stop {x['stop']:.2f}  tgt {x['target']:.2f}  "
                      f"(held {x['bars_held']}b)")


if __name__ == "__main__":
    main()
