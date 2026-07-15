import pytest

from src.ingest import normalize_price_history, PriceHistoryError


def _payload():
    return {
        "time": ["2026-01-02T14:30:00Z", "2026-01-05T14:30:00Z", "2026-01-06T14:30:00Z"],
        "open": [10.0, 11.0, 12.0],
        "high": [10.5, 11.5, 12.5],
        "low": [9.5, 10.5, 11.5],
        "close": [11.0, 12.0, None],  # last bar missing close -> dropped
        "volume": [1000, 2000, 3000],
    }


def test_normalizes_and_drops_null_close():
    rows = normalize_price_history(_payload(), symbol="AMD")
    assert len(rows) == 2
    assert rows[0] == {
        "symbol": "AMD", "date": "2026-01-02",
        "open": 10.0, "high": 10.5, "low": 9.5, "close": 11.0, "volume": 1000,
    }


def test_sorted_ascending_by_date():
    p = _payload()
    p["time"] = ["2026-01-06T14:30:00Z", "2026-01-02T14:30:00Z", "2026-01-05T14:30:00Z"]
    p["close"] = [12.0, 11.0, 12.0]  # no nulls so all kept
    rows = normalize_price_history(p, "X")
    assert [r["date"] for r in rows] == ["2026-01-02", "2026-01-05", "2026-01-06"]


def test_length_mismatch_raises():
    p = _payload()
    p["volume"] = [1000, 2000]  # short
    with pytest.raises(PriceHistoryError):
        normalize_price_history(p, "X")


def test_missing_array_raises():
    p = _payload()
    del p["high"]
    with pytest.raises(PriceHistoryError):
        normalize_price_history(p, "X")
