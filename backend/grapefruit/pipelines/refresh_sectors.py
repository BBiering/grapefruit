"""Weekly: backfill assets.sector / assets.industry via yfinance.

EODHD's bulk feed (our universe/market-cap source) carries no sector or
industry, and the per-symbol /fundamentals endpoint isn't on our plan. yfinance
(Yahoo Finance) covers sector/industry for US + EU tickers, using Yahoo's own
exchange suffixes — so we map our EODHD ticker ("BMW.XETRA") to Yahoo's
("BMW.DE") before looking it up.

Scoped to symbols that actually surface in the UI (winners + watchlist) and
don't yet have a sector, so it's a small, incremental call volume rather than
the whole universe. Names Yahoo can't resolve are left null and retried next
run.
"""
from __future__ import annotations

import logging

from grapefruit import storage


log = logging.getLogger(__name__)

# EODHD exchange suffix -> Yahoo Finance suffix. US is bare on Yahoo.
_EODHD_TO_YAHOO: dict[str, str] = {
    "US": "",
    "LSE": ".L",
    "XETRA": ".DE",
    "PA": ".PA",
    "ST": ".ST",
    "CO": ".CO",
    "HE": ".HE",
    "OL": ".OL",
}

_MAX_PER_RUN = 400  # bound Yahoo call volume per weekly run


def _yahoo_ticker(symbol: str) -> str | None:
    """'BMW.XETRA' -> 'BMW.DE'. Returns None for unknown exchanges."""
    if "." not in symbol:
        return None
    code, _, exchange = symbol.rpartition(".")
    if exchange not in _EODHD_TO_YAHOO:
        return None
    return f"{code}{_EODHD_TO_YAHOO[exchange]}"


def run() -> int:
    symbols = storage.symbols_needing_sector(limit=_MAX_PER_RUN)
    if not symbols:
        log.info("no symbols need sector backfill")
        return 0

    # Imported lazily so the dependency isn't required for other pipelines.
    import yfinance as yf

    updated = 0
    for symbol in symbols:
        yt = _yahoo_ticker(symbol)
        if not yt:
            continue
        try:
            info = yf.Ticker(yt).info
        except Exception as exc:  # noqa: BLE001 — Yahoo is flaky; skip & retry next run
            log.warning("yfinance failed for %s (%s): %s", symbol, yt, exc)
            continue
        sector = (info or {}).get("sector")
        industry = (info or {}).get("industry")
        if not sector and not industry:
            continue
        storage.update_asset_sector(symbol, sector=sector, industry=industry)
        updated += 1
        if updated % 50 == 0:
            log.info("backfilled sector for %d/%d", updated, len(symbols))

    log.info("refresh_sectors done: %d/%d symbols updated", updated, len(symbols))
    return updated
