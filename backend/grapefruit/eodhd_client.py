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

# Exchanges that make up the universe. EODHD has no unified "EU" exchange, so
# Europe is enumerated per-country. The symbol stored everywhere is the full
# EODHD ticker ("BMW.XETRA"), which is globally unique across these.
EXCHANGES: list[str] = ["US", "LSE", "XETRA", "PA", "ST", "CO", "HE", "OL"]

# Reporting currency of each exchange's MarketCapitalization / prices. Used to
# convert market cap to USD for the small-cap filter. LSE quotes in pence (GBX),
# so its cap is reported in GBP but prices in pence — only the cap conversion
# matters here, and EODHD reports LSE MarketCapitalization in GBP.
_EXCHANGE_CURRENCY: dict[str, str] = {
    "US": "USD",
    "LSE": "GBP",
    "XETRA": "EUR",
    "PA": "EUR",
    "ST": "SEK",
    "CO": "DKK",
    "HE": "EUR",
    "OL": "NOK",
}


def exchange_currency(exchange: str) -> str:
    return _EXCHANGE_CURRENCY.get(exchange, "USD")


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


def list_symbols(exchange: str = "US") -> list[dict]:
    """All symbols on `exchange`. Each item has Code/Name/Type/etc."""
    data = _get(f"exchange-symbol-list/{exchange}")
    return data if isinstance(data, list) else []


def fetch_eod(symbol: str, start: date, end: date) -> list[dict]:
    """Daily EOD bars for `symbol` in [start, end].

    `symbol` is a full EODHD ticker including the exchange suffix, e.g.
    "AAPL.US" or "BMW.XETRA". Items have date/OHLC/adjusted_close/volume.
    """
    data = _get(
        f"eod/{symbol}",
        {"period": "d", "from": start.isoformat(), "to": end.isoformat(), "order": "a"},
    )
    return data if isinstance(data, list) else []


def fetch_bulk_extended(exchange: str, symbols: list[str] | None = None) -> list[dict]:
    """EOD bulk last-day for `exchange` with extended fields.

    A single request returns one record per symbol with `code`, `name`, `type`,
    and `MarketCapitalization` (in the exchange's local currency) plus the
    latest OHLCV and moving averages. Pass `symbols` (bare codes, no suffix) to
    filter server-side; omit to pull the whole exchange in one call. This is the
    universe + metadata source: the per-symbol `/fundamentals` endpoint is not
    available on the current subscription tier.
    """
    params = {"filter": "extended"}
    if symbols:
        params["symbols"] = ",".join(symbols)
    data = _get(f"eod-bulk-last-day/{exchange}", params)
    return data if isinstance(data, list) else []


def fetch_fx_rate(currency: str) -> float | None:
    """Latest <currency>USD spot rate (e.g. 'SEK' -> ~0.10). USD returns 1.0."""
    if currency == "USD":
        return 1.0
    data = _get(f"real-time/{currency}USD.FOREX")
    if isinstance(data, dict):
        close = data.get("close")
        if isinstance(close, (int, float)) and close > 0:
            return float(close)
    return None


def fetch_news(symbol: str, start: date, end: date, limit: int = 50) -> list[dict]:
    """News articles mentioning `symbol` (full EODHD ticker) in [start, end]."""
    data = _get(
        "news",
        {
            "s": symbol,
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
