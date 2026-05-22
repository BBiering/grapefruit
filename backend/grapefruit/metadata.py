"""Finnhub-backed asset metadata (name, industry, exchange).

Finnhub's free `/stock/profile2` endpoint is far more reliable in cloud
environments than yfinance. It returns `name`, `finnhubIndustry`, and
`exchange`; there's no separate `sector` field on the free tier, so we map
`finnhubIndustry` to `industry` and leave `sector` empty.

Cached in DuckDB via storage.upsert_asset / load_asset.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

import httpx

from grapefruit import storage
from grapefruit.config import settings


log = logging.getLogger(__name__)

_FINNHUB_URL = "https://finnhub.io/api/v1/stock/profile2"


def fetch_metadata(symbol: str) -> dict:
    """Fetch fresh metadata from Finnhub. Never raises; missing fields are None."""
    row = {
        "symbol": symbol,
        "name": None,
        "exchange": None,
        "sector": None,
        "industry": None,
        "market_cap_usd": None,
        "refreshed_at": datetime.now(timezone.utc),
    }
    if not settings.finnhub_api_key:
        log.warning("FINNHUB_API_KEY not set; metadata for %s will be empty", symbol)
        return row
    try:
        resp = httpx.get(
            _FINNHUB_URL,
            params={"symbol": symbol, "token": settings.finnhub_api_key},
            timeout=15.0,
        )
        resp.raise_for_status()
        info = resp.json() or {}
        row["name"] = info.get("name") or None
        row["exchange"] = info.get("exchange") or None
        row["industry"] = info.get("finnhubIndustry") or None
        # Finnhub reports marketCapitalization in millions of USD.
        cap_m = info.get("marketCapitalization")
        if isinstance(cap_m, (int, float)) and cap_m > 0:
            row["market_cap_usd"] = float(cap_m) * 1_000_000
    except Exception as exc:  # noqa: BLE001
        log.warning("finnhub fetch failed for %s: %s", symbol, exc)
    return row


def get_or_fetch(symbol: str, refresh: bool = False) -> dict:
    symbol = symbol.upper()
    if not refresh:
        cached = storage.load_asset(symbol)
        if cached and cached.get("name"):
            return cached
    row = fetch_metadata(symbol)
    storage.upsert_asset(row)
    return row
