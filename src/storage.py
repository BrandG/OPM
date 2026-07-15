"""SQLite-backed local cache for symbols and daily bars.

Source-agnostic storage: whatever fetches data (yfinance bulk pulls, in-session
IBKR MCP, or a standalone ib_async daemon later) writes through here, and every
downstream stage (volatility, pivots, scoring, backtest) reads from here.

Bars are keyed by **symbol**, not IBKR contract_id — symbol is the natural
identity for the analysis pipeline; contract_id is an IBKR execution detail
stored on the symbols table and resolved lazily, only for names that go live.
Writes are idempotent so re-running a pull never duplicates rows.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterable, List, Optional

import pandas as pd


def _coerce_bar(row: dict) -> dict:
    """Coerce a bar row's fields to native Python types (or None).

    numpy/pandas scalars would otherwise be persisted by SQLite as opaque BLOBs.
    """
    def num(v, cast):
        return None if v is None else cast(v)

    return {
        "symbol": str(row["symbol"]).upper(),
        "date": str(row["date"]),
        "open": num(row.get("open"), float),
        "high": num(row.get("high"), float),
        "low": num(row.get("low"), float),
        "close": num(row.get("close"), float),
        "volume": num(row.get("volume"), int),
    }


_SCHEMA = """
CREATE TABLE IF NOT EXISTS symbols (
    symbol       TEXT PRIMARY KEY,
    contract_id  INTEGER,               -- nullable; filled when resolved for IBKR
    exchange     TEXT,
    currency     TEXT DEFAULT 'USD',
    description  TEXT,
    source       TEXT,                  -- 'yahoo' | 'ibkr'
    updated_at   TEXT
);
CREATE TABLE IF NOT EXISTS daily_bars (
    symbol   TEXT NOT NULL,
    date     TEXT NOT NULL,
    open     REAL,
    high     REAL,
    low      REAL,
    close    REAL,
    volume   INTEGER,
    PRIMARY KEY (symbol, date)
);
CREATE INDEX IF NOT EXISTS idx_bars_symbol ON daily_bars(symbol);
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);
CREATE TABLE IF NOT EXISTS setup_state (
    symbol       TEXT PRIMARY KEY,
    state        TEXT,              -- WATCHING | ARMED
    zone_id      TEXT,              -- support zone identity, to detect a changed setup
    side         TEXT,
    entry        REAL,
    stop         REAL,
    target       REAL,
    trade_score  REAL,
    sector       TEXT,
    updated_at   TEXT
);
CREATE TABLE IF NOT EXISTS paper_trades (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol        TEXT NOT NULL,
    side          TEXT NOT NULL DEFAULT 'long',
    status        TEXT NOT NULL,     -- PENDING | OPEN | CLOSED | CANCELLED
    signal_date   TEXT NOT NULL,     -- close date the armed setup fired (entry active next bar)
    entry         REAL,
    stop          REAL,
    target        REAL,
    sig_atr       REAL,              -- ATR at signal, for the slippage haircut
    planned_rr    REAL,
    shares        REAL,              -- sized fractional shares, for the constrained $ P&L view
    sector        TEXT,
    trade_score   REAL,
    corridor_pct  REAL,
    fill_date     TEXT,
    fill_price    REAL,
    exit_date     TEXT,
    exit_price    REAL,
    exit_reason   TEXT,              -- target | stop | time | expired
    bars_pending  INTEGER DEFAULT 0, -- bars observed while PENDING (entry-expiry counter)
    bars_held     INTEGER DEFAULT 0, -- bars observed while OPEN (time-stop counter)
    r_multiple    REAL,
    last_processed_date TEXT,        -- gap-safe advance cursor: last bar this row has seen
    created_at    TEXT,
    updated_at    TEXT
);
CREATE INDEX IF NOT EXISTS idx_paper_status ON paper_trades(status);
CREATE INDEX IF NOT EXISTS idx_paper_symbol ON paper_trades(symbol);
"""


class Store:
    """Thin wrapper over a SQLite database file."""

    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    @contextmanager
    def _conn(self):
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _init_schema(self) -> None:
        with self._conn() as conn:
            conn.executescript(_SCHEMA)

    # --- symbols -----------------------------------------------------------

    def upsert_symbol(
        self,
        symbol: str,
        contract_id: Optional[int] = None,
        exchange: Optional[str] = None,
        currency: str = "USD",
        description: Optional[str] = None,
        source: Optional[str] = None,
        updated_at: Optional[str] = None,
    ) -> None:
        """Insert/update a symbol record. Unspecified fields are left unchanged
        on update (so resolving a contract_id later won't wipe the source)."""
        with self._conn() as conn:
            conn.execute(
                """INSERT INTO symbols (symbol, contract_id, exchange, currency, description, source, updated_at)
                   VALUES (:symbol, :contract_id, :exchange, :currency, :description, :source, :updated_at)
                   ON CONFLICT(symbol) DO UPDATE SET
                       contract_id=COALESCE(excluded.contract_id, symbols.contract_id),
                       exchange=COALESCE(excluded.exchange, symbols.exchange),
                       currency=COALESCE(excluded.currency, symbols.currency),
                       description=COALESCE(excluded.description, symbols.description),
                       source=COALESCE(excluded.source, symbols.source),
                       updated_at=COALESCE(excluded.updated_at, symbols.updated_at)""",
                {
                    "symbol": symbol.upper(),
                    "contract_id": contract_id,
                    "exchange": exchange,
                    "currency": currency,
                    "description": description,
                    "source": source,
                    "updated_at": updated_at,
                },
            )

    def get_symbol(self, symbol: str) -> Optional[dict]:
        with self._conn() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM symbols WHERE symbol = ?", (symbol.upper(),)
            ).fetchone()
            return dict(row) if row else None

    def list_symbols(self) -> List[dict]:
        with self._conn() as conn:
            conn.row_factory = sqlite3.Row
            return [dict(r) for r in conn.execute("SELECT * FROM symbols ORDER BY symbol")]

    # --- bars --------------------------------------------------------------

    def upsert_bars(self, rows: Iterable[dict]) -> int:
        """Idempotently write daily bars (keyed by symbol). Returns rows written."""
        rows = [_coerce_bar(r) for r in rows]
        if not rows:
            return 0
        with self._conn() as conn:
            conn.executemany(
                """INSERT INTO daily_bars (symbol, date, open, high, low, close, volume)
                   VALUES (:symbol, :date, :open, :high, :low, :close, :volume)
                   ON CONFLICT(symbol, date) DO UPDATE SET
                       open=excluded.open, high=excluded.high, low=excluded.low,
                       close=excluded.close, volume=excluded.volume""",
                rows,
            )
        return len(rows)

    def get_bars(self, symbol: str) -> pd.DataFrame:
        """Return all daily bars for a symbol as a DataFrame indexed by date."""
        with self._conn() as conn:
            df = pd.read_sql_query(
                "SELECT date, open, high, low, close, volume FROM daily_bars "
                "WHERE symbol = ? ORDER BY date",
                conn,
                params=(symbol.upper(),),
                parse_dates=["date"],
            )
        return df.set_index("date")

    def bar_count(self, symbol: str) -> int:
        with self._conn() as conn:
            return conn.execute(
                "SELECT COUNT(*) FROM daily_bars WHERE symbol = ?", (symbol.upper(),)
            ).fetchone()[0]

    def symbols_with_bars(self) -> List[str]:
        with self._conn() as conn:
            return [r[0] for r in conn.execute(
                "SELECT DISTINCT symbol FROM daily_bars ORDER BY symbol")]

    # --- meta (small key/value: last regime, etc.) -------------------------

    def get_meta(self, key: str) -> Optional[str]:
        with self._conn() as conn:
            row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
            return row[0] if row else None

    def set_meta(self, key: str, value: str) -> None:
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO meta (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, str(value)))

    # --- per-symbol setup state (for the change-only alerter) --------------

    def get_setup_state(self, symbol: str) -> Optional[dict]:
        with self._conn() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT * FROM setup_state WHERE symbol = ?",
                               (symbol.upper(),)).fetchone()
            return dict(row) if row else None

    def all_setup_states(self) -> List[dict]:
        with self._conn() as conn:
            conn.row_factory = sqlite3.Row
            return [dict(r) for r in conn.execute("SELECT * FROM setup_state")]

    def set_setup_state(self, rec: dict) -> None:
        cols = ("symbol", "state", "zone_id", "side", "entry", "stop", "target",
                "trade_score", "sector", "updated_at")
        with self._conn() as conn:
            conn.execute(
                f"INSERT INTO setup_state ({','.join(cols)}) "
                f"VALUES ({','.join(':' + c for c in cols)}) "
                "ON CONFLICT(symbol) DO UPDATE SET " +
                ", ".join(f"{c}=excluded.{c}" for c in cols if c != "symbol"),
                {c: rec.get(c) for c in cols})

    def clear_setup_state(self, symbol: str) -> None:
        with self._conn() as conn:
            conn.execute("DELETE FROM setup_state WHERE symbol = ?", (symbol.upper(),))

    # --- forward paper-trade ledger ----------------------------------------

    _PAPER_COLS = (
        "symbol", "side", "status", "signal_date", "entry", "stop", "target",
        "sig_atr", "planned_rr", "shares", "sector", "trade_score", "corridor_pct",
        "fill_date", "fill_price", "exit_date", "exit_price", "exit_reason",
        "bars_pending", "bars_held", "r_multiple", "last_processed_date",
        "created_at", "updated_at",
    )

    def add_paper_trade(self, rec: dict) -> int:
        """Insert a new paper trade; returns its auto-assigned id."""
        cols = [c for c in self._PAPER_COLS]
        with self._conn() as conn:
            cur = conn.execute(
                f"INSERT INTO paper_trades ({','.join(cols)}) "
                f"VALUES ({','.join(':' + c for c in cols)})",
                {c: rec.get(c) for c in cols})
            return int(cur.lastrowid)

    def update_paper_trade(self, trade_id: int, fields: dict) -> None:
        """Patch selected columns of one paper trade (id never changes)."""
        cols = [c for c in fields if c in self._PAPER_COLS]
        if not cols:
            return
        with self._conn() as conn:
            conn.execute(
                f"UPDATE paper_trades SET {', '.join(f'{c}=:{c}' for c in cols)} "
                "WHERE id = :id",
                {**{c: fields[c] for c in cols}, "id": trade_id})

    def get_open_paper_trades(self) -> List[dict]:
        """PENDING or OPEN trades — the ones the daily advance must process."""
        with self._conn() as conn:
            conn.row_factory = sqlite3.Row
            return [dict(r) for r in conn.execute(
                "SELECT * FROM paper_trades WHERE status IN ('PENDING','OPEN') "
                "ORDER BY id")]

    def active_paper_keys(self) -> set:
        """(symbol, side) pairs with a live (PENDING/OPEN) trade — dedup guard so
        we don't open a second position in a name we're already in."""
        with self._conn() as conn:
            return {(r[0], r[1]) for r in conn.execute(
                "SELECT symbol, side FROM paper_trades WHERE status IN ('PENDING','OPEN')")}

    def all_paper_trades(self, status: Optional[str] = None) -> List[dict]:
        with self._conn() as conn:
            conn.row_factory = sqlite3.Row
            if status:
                rows = conn.execute(
                    "SELECT * FROM paper_trades WHERE status = ? ORDER BY id", (status,))
            else:
                rows = conn.execute("SELECT * FROM paper_trades ORDER BY id")
            return [dict(r) for r in rows]
