"""EODHD-backed asset metadata (name, exchange, market cap).

This subscription tier does not include the per-symbol `/fundamentals` endpoint
(it returns 403), so sector/industry are unavailable and stay None. Instead we
use the `eod-bulk-last-day/US?filter=extended` endpoint, which returns `name`
and `MarketCapitalization` (absolute USD) for the *entire US exchange in a single
request*. That one call costs the same quota whether filtered to one symbol or
not, so bulk refreshes pull the whole exchange at once via `bulk_refresh()`.

Cached in DuckDB via storage.upsert_asset / load_asset.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from grapefruit import eodhd_client, storage
from grapefruit.config import settings
from grapefruit.rate_limit import redact

log = logging.getLogger(__name__)


def _record_to_row(rec: dict, now: datetime) -> dict:
    cap = rec.get("MarketCapitalization")
    return {
        "symbol": (rec.get("code") or "").upper(),
        "name": rec.get("name") or None,
        "exchange": rec.get("exchange_short_name") or None,
        "sector": None,
        "industry": None,
        "market_cap_usd": float(cap) if isinstance(cap, (int, float)) and cap > 0 else None,
        "refreshed_at": now,
    }


def _empty_row(symbol: str) -> dict:
    return {
        "symbol": symbol,
        "name": None,
        "exchange": None,
        "sector": None,
        "industry": None,
        "market_cap_usd": None,
        "refreshed_at": datetime.now(timezone.utc),
    }


def fetch_metadata(symbol: str) -> dict:
    """Fetch fresh metadata for a single symbol. Never raises; missing fields are None."""
    if not settings.eodhd_api_key:
        log.warning("EODHD_API_KEY not set; metadata for %s will be empty", symbol)
        return _empty_row(symbol)
    try:
        recs = eodhd_client.fetch_bulk_extended([symbol])
        if recs:
            return _record_to_row(recs[0], datetime.now(timezone.utc))
    except Exception as exc:  # noqa: BLE001
        log.warning("eodhd metadata fetch failed for %s: %s", symbol, redact(str(exc)))
    return _empty_row(symbol)


def get_or_fetch(symbol: str, refresh: bool = False) -> dict:
    symbol = symbol.upper()
    if not refresh:
        cached = storage.load_asset(symbol)
        if cached and cached.get("name"):
            return cached
    row = fetch_metadata(symbol)
    storage.upsert_asset(row)
    return row


def bulk_refresh(symbols: list[str] | None = None) -> int:
    """Pull name + market cap for the whole US exchange in one call and upsert.

    If `symbols` is given, only those are written (others in the response are
    ignored). Returns the number of rows upserted with a usable name. This is the
    quota-efficient path: one API request regardless of universe size.
    """
    records = eodhd_client.fetch_bulk_extended()
    now = datetime.now(timezone.utc)
    wanted = {s.upper() for s in symbols} if symbols else None
    written = 0
    for rec in records:
        row = _record_to_row(rec, now)
        if not row["symbol"]:
            continue
        if wanted is not None and row["symbol"] not in wanted:
            continue
        storage.upsert_asset(row)
        if row["name"]:
            written += 1
    return written
