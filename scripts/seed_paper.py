"""One-off: seed the paper ledger from a saved watchlist CSV.

Used to enter the trades that were placed live before the ledger existed (the
2026-07-07 lark: ARES/TXN/PH/DOV) so the forward record and the real book start
from the same point. Seeds them as PENDING at the watchlist's signal date; the
normal daily advance then fills/exits them from cached bars, same as any signal.

Idempotent: skips any symbol+side already live in the ledger.

Usage:
    python scripts/seed_paper.py --csv reports/watchlist_2026-07-07.csv \
        --signal-date 2026-07-07 --symbols ARES,TXN,PH,DOV
"""

import argparse
import csv
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.storage import Store
from src.trades import size_position


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config.yaml")
    ap.add_argument("--csv", required=True)
    ap.add_argument("--signal-date", required=True,
                    help="close date the watchlist was generated (entry active next bar)")
    ap.add_argument("--symbols", default="",
                    help="comma-separated subset to seed; empty = all armed rows")
    args = ap.parse_args()

    cfg = yaml.safe_load(Path(args.config).read_text())
    t = cfg["trade"]
    store = Store(cfg["data"]["db_path"])
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    wanted = {s.strip().upper() for s in args.symbols.split(",") if s.strip()}
    active = store.active_paper_keys()

    seeded, skipped = [], []
    for row in csv.DictReader(Path(args.csv).open()):
        sym = row["symbol"].strip().upper()
        side = row.get("side", "long").strip() or "long"
        if wanted and sym not in wanted:
            continue
        if not int(row.get("armed", 1)):
            continue
        if (sym, side) in active:
            skipped.append(sym)
            continue
        entry, stop, target = float(row["entry"]), float(row["stop"]), float(row["target"])
        # ATR isn't in the CSV; back it out of the stop geometry
        # (stop = support_low - stop_atr_buffer*ATR is not recoverable, but the
        # slippage haircut needs an ATR scale — approximate it from risk width).
        sig_atr = round((entry - stop) / (t["stop_atr_buffer"] + t["entry_buffer_atr"]), 4)
        sizing = size_position(entry, stop, t["account_equity"], t["risk_pct"],
                               t["max_position_pct"])
        rec = {
            "symbol": sym, "side": side, "status": "PENDING",
            "signal_date": args.signal_date, "entry": entry, "stop": stop,
            "target": target, "sig_atr": sig_atr, "planned_rr": float(row.get("rr", 0) or 0),
            "shares": sizing["shares"], "sector": row.get("sector", "?"),
            "trade_score": float(row.get("trade_score", 0) or 0),
            "corridor_pct": float(row.get("corridor_pct", 0) or 0),
            "bars_pending": 0, "bars_held": 0,
            "last_processed_date": args.signal_date,
            "created_at": now, "updated_at": now,
        }
        store.add_paper_trade(rec)
        active.add((sym, side))
        seeded.append(sym)

    print(f"seeded {len(seeded)}: {', '.join(seeded) or '—'}")
    if skipped:
        print(f"skipped (already live): {', '.join(skipped)}")


if __name__ == "__main__":
    main()
