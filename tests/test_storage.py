from src.storage import Store


def test_symbol_roundtrip_and_partial_upsert(tmp_path):
    store = Store(tmp_path / "t.db")
    store.upsert_symbol("AMD", source="yahoo", updated_at="2026-07-07")
    got = store.get_symbol("amd")
    assert got["source"] == "yahoo"
    assert got["contract_id"] is None

    # Later resolve the IBKR contract_id without wiping the source (COALESCE).
    store.upsert_symbol("AMD", contract_id=4391, exchange="NASDAQ")
    got = store.get_symbol("AMD")
    assert got["contract_id"] == 4391
    assert got["source"] == "yahoo"       # preserved
    assert len(store.list_symbols()) == 1


def test_bars_upsert_is_idempotent(tmp_path):
    store = Store(tmp_path / "t.db")
    rows = [
        {"symbol": "AMD", "date": "2026-01-02", "open": 10, "high": 11, "low": 9, "close": 10.5, "volume": 100},
        {"symbol": "AMD", "date": "2026-01-05", "open": 10.5, "high": 12, "low": 10, "close": 11.5, "volume": 200},
    ]
    assert store.upsert_bars(rows) == 2
    store.upsert_bars(rows)  # re-run
    assert store.bar_count("AMD") == 2  # no duplicates

    df = store.get_bars("AMD")
    assert list(df["close"]) == [10.5, 11.5]
    assert df.index.name == "date"


def test_symbols_with_bars(tmp_path):
    store = Store(tmp_path / "t.db")
    store.upsert_bars([{"symbol": "KO", "date": "2026-01-02", "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1}])
    store.upsert_bars([{"symbol": "PG", "date": "2026-01-02", "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1}])
    assert store.symbols_with_bars() == ["KO", "PG"]


def test_empty_bars_noop(tmp_path):
    store = Store(tmp_path / "t.db")
    assert store.upsert_bars([]) == 0
