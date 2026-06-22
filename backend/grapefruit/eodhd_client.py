"""EODHD-backed data client (universe, daily bars, fundamentals, news).

A single HTTP provider replacing Alpaca + Finnhub. EODHD allows 1000 calls/min
and 100,000 calls/day, so per-symbol fetches are practical when run concurrently
under the shared EODHD_BUCKET (900/min, leaving headroom).

All endpoints take `api_token` and return JSON when `fmt=json` is passed. Errors
are redacted before logging so the token never leaks. HTTP 429 is retried,
honoring Retry-After.
"""
from __future__ import annotations

import logging
import time
from datetime import date

import httpx

from grapefruit.config import settings
from grapefruit.rate_limit import EODHD_BUCKET, redact

log = logging.getLogger(__name__)

_BASE_URL = "https://eodhd.com/api"
_MAX_RETRIES = 3
_MAX_RETRY_SLEEP = 60.0
_TIMEOUT = 30.0


def _require_key() -> str:
    if not settings.eodhd_api_key:
        raise RuntimeError(
            "EODHD API key not set. Copy .env.example to .env and fill EODHD_API_KEY."
        )
    return settings.eodhd_api_key


def _parse_retry_after(header: str | None) -> float:
    if not header:
        return 5.0
    try:
        return min(float(header), _MAX_RETRY_SLEEP)
    except ValueError:
        return 5.0


def _get(path: str, params: dict | None = None):
    """GET {BASE}/{path} as JSON with rate-limiting and 429 retry."""
    query = {"api_token": _require_key(), "fmt": "json"}
    if params:
        query.update(params)
    url = f"{_BASE_URL}/{path}"
    for attempt in range(_MAX_RETRIES):
        EODHD_BUCKET.acquire()
        try:
            resp = httpx.get(url, params=query, timeout=_TIMEOUT)
        except Exception as exc:  # noqa: BLE001 — network hiccup; retry
            if attempt + 1 >= _MAX_RETRIES:
                raise
            log.warning("eodhd request failed (%s); retrying", redact(str(exc)))
            time.sleep(2 ** attempt)
            continue
        if resp.status_code == 429:
            retry_after = _parse_retry_after(resp.headers.get("Retry-After"))
            log.warning(
                "eodhd 429 on %s; sleeping %.1fs (attempt %d/%d)",
                path, retry_after, attempt + 1, _MAX_RETRIES,
            )
            time.sleep(retry_after)
            continue
        resp.raise_for_status()
        return resp.json()
    log.warning("eodhd gave up on %s after %d 429s", path, _MAX_RETRIES)
    return None


def list_symbols() -> list[dict]:
    """All symbols on the unified US exchange. Each item has Code/Name/Type/etc."""
    data = _get("exchange-symbol-list/US")
    return data if isinstance(data, list) else []


def fetch_eod(symbol: str, start: date, end: date) -> list[dict]:
    """Daily EOD bars for `symbol` in [start, end]. Items have date/OHLC/adjusted_close/volume."""
    data = _get(
        f"eod/{symbol}.US",
        {"period": "d", "from": start.isoformat(), "to": end.isoformat(), "order": "a"},
    )
    return data if isinstance(data, list) else []


def fetch_bulk_extended(symbols: list[str] | None = None) -> list[dict]:
    """EOD bulk last-day for the US exchange with extended fields.

    A single request returns one record per symbol with `name` and
    `MarketCapitalization` (absolute USD) plus the latest OHLCV and moving
    averages. Pass `symbols` to filter server-side; omit to pull the whole
    exchange in one call. Used for metadata because the per-symbol
    `/fundamentals` endpoint requires a higher subscription tier.
    """
    params = {"filter": "extended"}
    if symbols:
        params["symbols"] = ",".join(symbols)
    data = _get("eod-bulk-last-day/US", params)
    return data if isinstance(data, list) else []


def fetch_news(symbol: str, start: date, end: date, limit: int = 50) -> list[dict]:
    """News articles mentioning `symbol` in [start, end]."""
    data = _get(
        "news",
        {
            "s": f"{symbol}.US",
            "from": start.isoformat(),
            "to": end.isoformat(),
            "limit": limit,
        },
    )
    return data if isinstance(data, list) else []


def fetch_earnings_calendar(start: date, end: date, symbols: list[str] | None = None) -> list[dict]:
    """Upcoming earnings dates in [start, end] for US tickers.

    Optionally filter by `symbols`. Each item has at least:
    `code` (symbol), `date`, `report_date`, `estimate`, `revenue_estimate`,
    `actual`, `difference`, `percent`. EODHD's docs:
    https://eodhd.com/financial-apis/calendar-upcoming-earnings-ipos-splits/
    """
    params = {"from": start.isoformat(), "to": end.isoformat()}
    if symbols:
        params["symbols"] = ",".join(f"{s}.US" for s in symbols)
    data = _get("calendar/earnings", params)
    if isinstance(data, dict):
        return data.get("earnings", [])
    return data if isinstance(data, list) else []
