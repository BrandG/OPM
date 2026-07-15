"""Resolve a ticker symbol to its IBKR US-primary stock contract_id.

`search_contracts` returns a very noisy list (foreign listings, leveraged
ETFs, bonds, funds). This module picks the correct US-primary common-stock row
as a pure function so it can be unit-tested against captured fixtures without a
live connection.
"""

from __future__ import annotations

from typing import Optional

# US primary listing venues, in rough order of preference. S&P 500 names list on
# NASDAQ or NYSE; the others are included so ETFs/edge cases still resolve.
_PRIMARY_EXCHANGES = ("NYSE", "NASDAQ", "ARCA", "BATS", "AMEX")


def _has_stock_section(row: dict) -> bool:
    return any(
        sec.get("security_type") == "STK" for sec in row.get("sections", [])
    )


def pick_us_primary(search_results: dict, symbol: str) -> Optional[dict]:
    """Return the US-primary common-stock contract for `symbol`, or None.

    Args:
        search_results: the raw JSON dict returned by search_contracts
            (expects a top-level "results" list).
        symbol: the ticker we searched for, e.g. "AMD".

    Returns:
        A normalized dict with keys: symbol, contract_id, exchange, description,
        currency. None if no confident US-primary stock match exists.
    """
    want = symbol.strip().upper()
    rows = search_results.get("results", []) if search_results else []

    candidates = [
        row
        for row in rows
        # Bond/issuer rows have no "symbol" key at all -> excluded here.
        if str(row.get("symbol", "")).upper() == want
        and row.get("country_code") == "US"
        and row.get("underlying_contract_id") is not None
        and _has_stock_section(row)
    ]
    if not candidates:
        return None

    def rank(row: dict) -> int:
        exch = row.get("exchange", "")
        return _PRIMARY_EXCHANGES.index(exch) if exch in _PRIMARY_EXCHANGES else len(_PRIMARY_EXCHANGES)

    best = min(candidates, key=rank)
    return {
        "symbol": want,
        "contract_id": int(best["underlying_contract_id"]),
        "exchange": best.get("exchange"),
        "description": best.get("description"),
        "currency": "USD",
    }
