"""Weekly: refresh market cap (USD) and name for the existing universe.

`refresh_universe` selects membership; this keeps `market_cap_usd` fresh for the
symbols already in `assets` without re-applying the small-cap filter (so a name
doesn't churn out of the dashboard mid-week on a small FX wobble). One bulk call
per exchange, market cap converted to USD via the FOREX rate.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from grapefruit import eodhd_client, storage


log = logging.getLogger(__name__)


def run() -> int:
    existing = set(storage.symbols_in_assets())
    if not existing:
        log.warning("no symbols in `assets`; run refresh_universe first")
        return 0

    now = datetime.now(timezone.utc)
    updated: list[dict] = []

    for exchange in eodhd_client.EXCHANGES:
        currency = eodhd_client.exchange_currency(exchange)
        fx = eodhd_client.fetch_fx_rate(currency)
        if fx is None:
            log.warning("no FX rate for %s (%s); skipping", exchange, currency)
            continue

        for r in eodhd_client.fetch_bulk_extended(exchange):
            code = r.get("code") or r.get("Code")
            if not code:
                continue
            symbol = f"{code}.{exchange}"
            if symbol not in existing:
                continue
            mc = r.get("MarketCapitalization") or r.get("market_capitalization")
            cap_usd = float(mc) * fx if isinstance(mc, (int, float)) and mc > 0 else None
            updated.append(
                {
                    "symbol": symbol,
                    "name": r.get("name") or r.get("Name"),
                    "exchange": exchange,
                    "sector": None,
                    "industry": None,
                    "market_cap_usd": cap_usd,
                    "refreshed_at": now,
                }
            )

    n = storage.upsert_assets(updated)
    log.info("refreshed fundamentals for %d/%d universe symbols", n, len(existing))
    return n
