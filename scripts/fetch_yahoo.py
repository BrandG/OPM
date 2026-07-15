"""Bulk-populate the local cache with daily bars from Yahoo (yfinance).

Symbol-keyed, source-agnostic: this fills bars for the whole S&P 500 universe
without needing IBKR contract resolution. IBKR is reserved for live quotes and
execution on the handful of names that survive filtering. Daily bars from Yahoo
match IBKR to the cent for liquid names (verified on AMD), so detection and
backtesting on this data carry over cleanly.

Usage:
    python scripts/fetch_yahoo.py [--config config.yaml] [--period 2y] [--limit N]
"""

import argparse
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import warnings

warnings.filterwarnings("ignore")

import yfinance as yf

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.storage import Store


def load_universe(path: str) -> list[str]:
    syms = []
    for line in Path(path).read_text().splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            syms.append(line.upper())
    return syms


def to_yahoo(symbol: str) -> str:
    # Yahoo uses a dash for class shares (BRK.B -> BRK-B).
    return symbol.replace(".", "-")


def rows_from_frame(sub, symbol: str) -> list[dict]:
    rows = []
    for idx, r in sub.iterrows():
        close = r.get("Close")
        if close is None or close != close:  # NaN guard
            continue
        rows.append({
            "symbol": symbol,
            "date": idx.strftime("%Y-%m-%d"),
            "open": r.get("Open"),
            "high": r.get("High"),
            "low": r.get("Low"),
            "close": close,
            "volume": r.get("Volume"),
        })
    return rows


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config.yaml")
    ap.add_argument("--period", default="2y", help="yfinance period (e.g. 1y, 2y, 5y)")
    ap.add_argument("--batch", type=int, default=50)
    ap.add_argument("--limit", type=int, default=None, help="only fetch first N symbols (debug)")
    args = ap.parse_args()

    import yaml
    cfg = yaml.safe_load(Path(args.config).read_text())
    store = Store(cfg["data"]["db_path"])
    universe = load_universe(cfg["universe"]["source_file"])
    if args.limit:
        universe = universe[: args.limit]

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    ok, empty, total_bars = [], [], 0

    for start in range(0, len(universe), args.batch):
        batch = universe[start : start + args.batch]
        ymap = {to_yahoo(s): s for s in batch}
        data = yf.download(
            tickers=list(ymap.keys()), period=args.period, interval="1d",
            group_by="ticker", auto_adjust=False, threads=True, progress=False,
        )
        multi = hasattr(data.columns, "levels")
        for ysym, sym in ymap.items():
            try:
                sub = data[ysym] if multi else data
            except KeyError:
                empty.append(sym)
                continue
            sub = sub.dropna(how="all")
            rows = rows_from_frame(sub, sym)
            if not rows:
                empty.append(sym)
                continue
            store.upsert_symbol(sym, source="yahoo", updated_at=now)
            total_bars += store.upsert_bars(rows)
            ok.append(sym)
        print(f"  batch {start//args.batch + 1}: {len(batch)} requested, "
              f"{len(ok)} ok cumulative")
        time.sleep(1.0)  # be polite between batches

    print(f"\nDone. {len(ok)}/{len(universe)} symbols populated, {total_bars} bars.")
    if empty:
        print(f"No data for {len(empty)}: {empty}")


if __name__ == "__main__":
    main()
