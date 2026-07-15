"""Bootstrap ingest driver.

Reads a captured get_price_history JSON payload from a file and writes it into
the local cache. This is how we populate the store from in-session MCP pulls
until a standalone fetch backend exists.

Usage:
    python scripts/ingest_json.py <symbol> <contract_id> <payload.json> [--db PATH]
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.ingest import normalize_price_history
from src.storage import Store


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("symbol")
    ap.add_argument("contract_id", type=int)
    ap.add_argument("payload", help="path to a get_price_history JSON file")
    ap.add_argument("--db", default="data/scanner.db")
    ap.add_argument("--exchange", default=None)
    ap.add_argument("--resolved-at", default="unknown")
    args = ap.parse_args()

    raw = json.loads(Path(args.payload).read_text())
    rows = normalize_price_history(raw, args.symbol)

    store = Store(args.db)
    store.upsert_symbol(
        args.symbol,
        contract_id=args.contract_id,
        exchange=args.exchange,
        source="ibkr",
        updated_at=args.resolved_at,
    )
    written = store.upsert_bars(rows)

    df = store.get_bars(args.symbol)
    print(f"{args.symbol}: ingested {written} bars, store now holds {len(df)}")
    if not df.empty:
        print(f"  date range: {df.index.min().date()} -> {df.index.max().date()}")
        print(f"  last close: {df['close'].iloc[-1]}")


if __name__ == "__main__":
    main()
