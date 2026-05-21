from datetime import date

import pandas as pd
import pytest

from grapefruit import config, storage


@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    db_path = tmp_path / "test.duckdb"
    monkeypatch.setattr(config, "DUCKDB_PATH", db_path)
    monkeypatch.setattr(storage, "DUCKDB_PATH", db_path, raising=False)
    monkeypatch.setattr(storage, "_conn", None)
    storage.init_db()
    yield
    if storage._conn is not None:
        storage._conn.close()
        monkeypatch.setattr(storage, "_conn", None)


def test_upsert_and_load_roundtrip():
    df = pd.DataFrame(
        [
            {"symbol": "AAA", "ts": date(2024, 1, 1), "open": 1.0, "high": 1.2, "low": 0.9, "close": 1.1, "volume": 100},
            {"symbol": "AAA", "ts": date(2024, 1, 2), "open": 1.1, "high": 1.3, "low": 1.0, "close": 1.25, "volume": 110},
            {"symbol": "BBB", "ts": date(2024, 1, 1), "open": 5.0, "high": 5.1, "low": 4.9, "close": 5.05, "volume": 50},
        ]
    )
    assert storage.upsert_bars(df) == 3

    aaa = storage.load_symbol("AAA")
    assert len(aaa) == 2
    assert storage.last_ts("AAA") == date(2024, 1, 2)
    assert sorted(storage.symbols_with_bars()) == ["AAA", "BBB"]


def test_hits_save_and_query():
    rows = [
        {
            "symbol": "AAA",
            "start_ts": date(2024, 1, 1),
            "end_ts": date(2024, 6, 1),
            "trough_price": 1.0,
            "peak_price": 15.0,
            "multiplier": 15.0,
        },
        {
            "symbol": "BBB",
            "start_ts": date(2024, 2, 1),
            "end_ts": date(2024, 7, 1),
            "trough_price": 2.0,
            "peak_price": 22.0,
            "multiplier": 11.0,
        },
    ]
    storage.save_hits(rows, window_days=130, threshold=10.0)
    out = storage.query_hits(window_weeks=26, min_multiplier=12.0)
    assert len(out) == 1
    assert out[0]["symbol"] == "AAA"
