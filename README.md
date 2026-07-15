# OPM

A long-only swing-trading support/resistance scanner for a personal IBKR
account. Ranks the most volatile S&P 500 names, detects support/resistance
zones on daily bars, filters for tradable support→resistance corridors, and
(eventually) reports/executes bracket-order setups.

Design constraints: long-only, swing horizon (no intraday account access during
the workday), small account (~$3.6k) using **fractional shares**.

## Status

Phase 1 (data layer) — **done**. Everything below is built and tested.

## Architecture

- **Data source:** Interactive Brokers, via the MCP tools available in the
  Claude Code session (`search_contracts`, `get_price_history`). These are NOT
  callable from a standalone script — see "Runtime decision" below.
- **Local cache:** SQLite (`data/scanner.db`), the single source of truth every
  downstream stage reads from. Populated by bootstrapping MCP pulls through
  `scripts/ingest_json.py`.

### Runtime decision (deferred)

The autonomous 30-minute runner will use one of:
- **A** — standalone Python daemon via `ib_async` + IB Gateway/TWS, or
- **B** — a scheduled Claude agent using the MCP tools.

Not decided yet; nothing in the detection/scoring/backtest math depends on it,
because all of it reads from the local cache.

## Layout

```
config.yaml            all tunable parameters (swept by the backtester later)
src/resolver.py        symbol -> IBKR US-primary contract_id (pure fn)
src/ingest.py          get_price_history JSON -> normalized daily bars (pure fn)
src/storage.py         SQLite cache: symbols + daily_bars
scripts/ingest_json.py bootstrap driver: captured JSON payload -> cache
tests/                 pytest suite
```

## Setup

```bash
python3 -m venv .venv
./.venv/bin/pip install -r requirements.txt
./.venv/bin/python -m pytest -q
```

## Build order (remaining)

2. Volatility ranker (ATR% on daily bars) + optional trend/choppiness filter
3. Pivot detection + ATR-normalized clustering  ← **validate on charts before scoring**
4. Zone scoring (touches, V-shape, psych, containment, recency)
5. Corridor filter + fractional-share trade construction (entry/stop/target, R/R gate)
6. Backtester  ← must show an edge before wiring execution
7. Scheduler + per-(symbol,zone) state machine + alerting
8. Execution (IBKR bracket orders)
```
