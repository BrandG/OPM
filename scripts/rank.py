"""Rank the configured universe by ATR% and print the table.

Reads all parameters from config.yaml and the universe from the configured
source file. Bars must already be in the local cache (see scripts/ingest_json.py
or the seed manifest).

Usage:
    python scripts/rank.py [--config config.yaml]
"""

import argparse
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.storage import Store
from src.volatility import rank_universe


def load_universe(path: str) -> list[str]:
    syms = []
    for line in Path(path).read_text().splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            syms.append(line.upper())
    return syms


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config.yaml")
    args = ap.parse_args()

    cfg = yaml.safe_load(Path(args.config).read_text())
    store = Store(cfg["data"]["db_path"])
    universe = load_universe(cfg["universe"]["source_file"])

    period = cfg["volatility"]["atr_period"]
    min_bars = cfg["volatility"].get("min_bars") or period
    ranked = rank_universe(
        store,
        universe,
        period=period,
        top_n=cfg["volatility"].get("top_n"),
        max_share_price=cfg["universe"].get("max_share_price"),
        min_bars=min_bars,
    )
    if ranked.empty:
        print("No ranked symbols — is the cache populated?")
        return

    # Surface anything excluded for thin history rather than dropping silently.
    excluded = [
        (sym, store.bar_count(sym))
        for sym in universe
        if 0 < store.bar_count(sym) < min_bars
    ]
    if excluded:
        names = ", ".join(f"{s} ({n})" for s, n in sorted(excluded, key=lambda x: x[1]))
        print(f"Excluded {len(excluded)} thin-history name(s) (<{min_bars} bars): {names}\n")

    ranked = ranked.copy()
    ranked["atr_pct"] = (ranked["atr_pct"] * 100).round(2).astype(str) + "%"
    print(ranked.to_string(index=False))


if __name__ == "__main__":
    main()
