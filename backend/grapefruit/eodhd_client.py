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

# Exchanges that make up the universe. Focus is US small-caps; European
# exchanges are excluded (user decision to concentrate on US retail-accessible
# names). The symbol stored everywhere is the full EODHD ticker (e.g. "DRUG.US").
EXCHANGES: list[str] = ["US"]

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


# Currencies that mark a symbol as NATIVE to the exchange (vs a foreign
# cross-listing). EODHD's per-exchange feeds are polluted with foreign
# companies cross-listed under cryptic codes (e.g. "0RA9.LSE" is the French
# biotech Abivax, whose real listing is ABVX.PA). Those are priced in their
# home currency, not the exchange's, so currency is the discriminator. LSE
# natives quote in pence (GBX) or pounds (GBP).
_NATIVE_CURRENCIES: dict[str, set[str]] = {
    "US": {"USD"},
    "LSE": {"GBX", "GBP"},
    "XETRA": {"EUR"},
    "PA": {"EUR"},
    "ST": {"SEK"},
    "CO": {"DKK"},
    "HE": {"EUR"},
    "OL": {"NOK"},
}


# Real venues we accept under the EODHD "US" umbrella. EODHD's US list lumps
# ~12k OTC / pink-sheet names (Exchange in PINK, OTCQB, OTCGREY, OTCQX, OTCCE,
# OTCMKTS, OTCBB, OTCPK) in with the real exchanges. OTC tickers are illiquid
# and their stale/near-zero prints fabricate absurd multipliers (47000x), so we
# keep only the proper venues. Non-US exchanges aren't subdivided this way.
_US_REAL_EXCHANGES: set[str] = {
    "NYSE", "NASDAQ", "AMEX", "BATS", "NYSE ARCA", "NYSE MKT", "US",
}


def native_symbol_meta(exchange: str) -> dict[str, dict]:
    """Map of {bare_code: {name, isin, currency}} for NATIVE common stocks on
    `exchange` (foreign cross-listings and US OTC/pink-sheets filtered out).

    Reads the exchange-symbol-list endpoint, which — unlike the bulk feed —
    carries Currency, Isin, and the real venue (Exchange). Used by
    refresh_universe to reject phantom cross-listings + OTC names and to dedup
    the same company across exchanges by ISIN.
    """
    native = _NATIVE_CURRENCIES.get(exchange, {_EXCHANGE_CURRENCY.get(exchange, "USD")})
    out: dict[str, dict] = {}
    for r in list_symbols(exchange):
        if r.get("Type") != "Common Stock":
            continue
        code = r.get("Code")
        if not code or r.get("Currency") not in native:
            continue
        # US: keep only real exchanges, drop OTC/pink-sheets.
        if exchange == "US" and r.get("Exchange") not in _US_REAL_EXCHANGES:
            continue
        out[code] = {
            "name": r.get("Name"),
            "isin": r.get("Isin"),
            "currency": r.get("Currency"),
            "venue": r.get("Exchange"),
        }
    return out


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
        if resp.status_code == 403:
            # Endpoint not available on the current subscription tier (e.g.
            # /fundamentals, calendar/earnings). Treat as "no data" so one
            # gated endpoint doesn't abort the whole run.
            log.warning("eodhd 403 on %s (not on current plan); skipping", path)
            return None
        if resp.status_code >= 400:
            # Never call raise_for_status(): its message embeds the request URL,
            # which contains the api_token. Redact before logging/raising.
            raise RuntimeError(
                redact(f"eodhd {resp.status_code} on {path}: {resp.text[:200]}")
            )
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


def fetch_fundamentals(symbol: str) -> dict | None:
    """Per-symbol fundamentals (`/fundamentals/{symbol}`). Returns the parsed
    JSON dict, or None if the endpoint is gated on the current plan (403) or the
    symbol has no data. `symbol` is a full EODHD ticker, e.g. "AAPL.US".

    NOTE: on the current EODHD tier this endpoint is typically NOT available and
    returns 403 (handled by `_get`, which yields None). The screener treats a
    None result as 'no quality signal' and falls back to a neutral score.
    """
    data = _get(f"fundamentals/{symbol}")
    return data if isinstance(data, dict) else None


def fundamentals_highlights(fundamentals: dict | None) -> tuple[float | None, float | None]:
    """Extract (net_income_ttm, profit_margin) from a /fundamentals payload.

    Returns (None, None) when the payload is missing or lacks the Highlights
    block. profit_margin is a fraction (0.15 == 15%).

    If NetIncomeTTM is not available, derive it from RevenueTTM × ProfitMargin."""
    if not fundamentals:
        return None, None
    hi = fundamentals.get("Highlights") or {}
    ni = hi.get("NetIncomeTTM") if isinstance(hi.get("NetIncomeTTM"), (int, float)) else None
    pm = hi.get("ProfitMargin") if isinstance(hi.get("ProfitMargin"), (int, float)) else None

    # Derive net income if not available but we have revenue and margin
    if ni is None and pm is not None:
        revenue = hi.get("RevenueTTM") if isinstance(hi.get("RevenueTTM"), (int, float)) else None
        if revenue is not None and revenue > 0:
            ni = float(revenue) * float(pm)

    return (float(ni) if ni is not None else None, float(pm) if pm is not None else None)


def fetch_insider_transactions(symbol: str, limit: int = 100) -> list[dict]:
    """SEC Form 4 insider transactions for `symbol` (`/insider-transactions`).

    Returns [] if the endpoint is gated on the current plan (403) or there's no
    data. `symbol` is a full EODHD ticker, e.g. "AAPL.US".
    """
    data = _get("insider-transactions", {"code": symbol, "limit": limit})
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
