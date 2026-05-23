"""Finnhub-backed asset metadata (name, industry, exchange, market cap).

Finnhub's free `/stock/profile2` endpoint is far more reliable in cloud
environments than yfinance. It returns `name`, `finnhubIndustry`,
`exchange`, and `marketCapitalization` (in millions of USD). There's no
separate `sector` field on the free tier.

Calls are rate-limited via the shared FINNHUB_BUCKET (55/min) and the
function retries on HTTP 429 honoring Retry-After. Cached in DuckDB via
storage.upsert_asset / load_asset.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone

import httpx

from grapefruit import storage
from grapefruit.config import settings
from grapefruit.rate_limit import FINNHUB_BUCKET, redact


log = logging.getLogger(__name__)

_FINNHUB_URL = "https://finnhub.io/api/v1/stock/profile2"
_MAX_RETRIES = 3
_MAX_RETRY_SLEEP = 60.0


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
        info = _get_profile(symbol)
        if info is None:
            return row
        row["name"] = info.get("name") or None
        row["exchange"] = info.get("exchange") or None
        row["industry"] = info.get("finnhubIndustry") or None
        cap_m = info.get("marketCapitalization")
        if isinstance(cap_m, (int, float)) and cap_m > 0:
            row["market_cap_usd"] = float(cap_m) * 1_000_000
    except Exception as exc:  # noqa: BLE001
        log.warning("finnhub fetch failed for %s: %s", symbol, redact(str(exc)))
    return row


def _get_profile(symbol: str) -> dict | None:
    """GET /stock/profile2 with rate-limiting and 429 retry. Returns parsed JSON or None."""
    for attempt in range(_MAX_RETRIES):
        FINNHUB_BUCKET.acquire()
        resp = httpx.get(
            _FINNHUB_URL,
            params={"symbol": symbol, "token": settings.finnhub_api_key},
            timeout=15.0,
        )
        if resp.status_code == 429:
            retry_after = _parse_retry_after(resp.headers.get("Retry-After"))
            log.warning(
                "finnhub 429 for %s; sleeping %.1fs (attempt %d/%d)",
                symbol, retry_after, attempt + 1, _MAX_RETRIES,
            )
            time.sleep(retry_after)
            continue
        resp.raise_for_status()
        data = resp.json()
        return data if isinstance(data, dict) else None
    log.warning("finnhub gave up on %s after %d 429s", symbol, _MAX_RETRIES)
    return None


def _parse_retry_after(header: str | None) -> float:
    if not header:
        return 5.0
    try:
        return min(float(header), _MAX_RETRY_SLEEP)
    except ValueError:
        return 5.0


def get_or_fetch(symbol: str, refresh: bool = False) -> dict:
    symbol = symbol.upper()
    if not refresh:
        cached = storage.load_asset(symbol)
        if cached and cached.get("name"):
            return cached
    row = fetch_metadata(symbol)
    storage.upsert_asset(row)
    return row
