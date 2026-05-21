"""Lazy yfinance-backed asset metadata (name, sector, industry, exchange).

Cached in DuckDB via storage.upsert_asset / load_asset. yfinance is rate-limited
and flaky, so callers should treat failures as soft (returning a row with None
fields) and re-try later.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from grapefruit import storage


log = logging.getLogger(__name__)


def fetch_metadata(symbol: str) -> dict:
    """Fetch fresh metadata from yfinance. Never raises; missing fields are None."""
    row = {
        "symbol": symbol,
        "name": None,
        "exchange": None,
        "sector": None,
        "industry": None,
        "refreshed_at": datetime.now(timezone.utc),
    }
    try:
        import yfinance as yf

        info = yf.Ticker(symbol).info or {}
        row["name"] = info.get("longName") or info.get("shortName")
        row["exchange"] = info.get("exchange") or info.get("fullExchangeName")
        row["sector"] = info.get("sector")
        row["industry"] = info.get("industry")
    except Exception as exc:  # noqa: BLE001
        log.warning("yfinance fetch failed for %s: %s", symbol, exc)
    return row


def get_or_fetch(symbol: str, refresh: bool = False) -> dict:
    symbol = symbol.upper()
    if not refresh:
        cached = storage.load_asset(symbol)
        if cached:
            return cached
    row = fetch_metadata(symbol)
    storage.upsert_asset(row)
    return row
