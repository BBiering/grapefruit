"""Postgres-backed storage tests.

Skipped unless DATABASE_URL points at a throwaway Postgres / Supabase project.
The tests destroy and recreate every table in the public schema, so DO NOT
point this at a production DB.
"""
import os
from datetime import date

import pandas as pd
import pytest


pytestmark = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL"),
    reason="requires DATABASE_URL pointing at a throwaway Postgres",
)


@pytest.fixture(autouse=True)
def fresh_schema(monkeypatch):
    # Force a fresh pool with the test DATABASE_URL.
    from grapefruit import config, storage

    monkeypatch.setattr(config.settings, "database_url", os.environ["DATABASE_URL"])
    monkeypatch.setattr(storage, "_pool", None)
    storage.init_db()
    with storage._conn() as con:  # type: ignore[attr-defined]
        with con.cursor() as cur:
            cur.execute(
                "TRUNCATE bars, hits, assets, catalysts, app_state, news_cache RESTART IDENTITY"
            )
    yield


def test_upsert_and_load_roundtrip():
    from grapefruit import storage

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
    from grapefruit import storage

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
