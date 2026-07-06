"""Weekly: backfill assets.sector / assets.industry via EODHD fundamentals.

EODHD's bulk feed (our universe/market-cap source) carries no sector or
industry, but the per-symbol /fundamentals endpoint provides General.Sector
and General.Industry for most stocks.

Scoped to symbols that actually surface in the UI (winners + watchlist) and
don't yet have a sector, so it's a small, incremental call volume rather than
the whole universe. Symbols EODHD can't resolve are left null and retried next
run.
"""
from __future__ import annotations

import logging

from grapefruit import eodhd_client, storage


log = logging.getLogger(__name__)

_MAX_PER_RUN = 400  # bound EODHD call volume per weekly run


def run() -> int:
    symbols = storage.symbols_needing_sector(limit=_MAX_PER_RUN)
    if not symbols:
        log.info("no symbols need sector backfill")
        return 0

    updated = 0
    for symbol in symbols:
        try:
            fund = eodhd_client.fetch_fundamentals(symbol)
        except Exception as exc:  # noqa: BLE001 — API is flaky; skip & retry next run
            log.warning("EODHD fundamentals failed for %s: %s", symbol, exc)
            continue

        if not fund:
            continue

        general = fund.get("General") or {}
        sector = general.get("Sector")
        industry = general.get("Industry")

        if not sector and not industry:
            continue

        storage.update_asset_sector(symbol, sector=sector, industry=industry)
        updated += 1
        if updated % 50 == 0:
            log.info("backfilled sector for %d/%d", updated, len(symbols))

    log.info("refresh_sectors done: %d/%d symbols updated", updated, len(symbols))
    return updated
