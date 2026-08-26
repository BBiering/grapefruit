"""Weekly: backfill assets.sector / assets.industry via EODHD fundamentals,
pruning non-biotech names deterministically as they are classified.

EODHD's bulk feed (our universe/market-cap source) carries no sector or
industry, but the per-symbol /fundamentals endpoint provides General.Sector
and General.Industry for most stocks.

Classification and pruning is per-symbol and deterministic:
- fundamentals resolve to industry == 'Biotechnology'  -> keep, store sector
- fundamentals resolve to a different industry         -> delete immediately
- fundamentals fail or are missing                     -> leave NULL, retry next run

Symbols not reached this run (the batch budget) stay NULL by design; they are
simply "next in the queue", not failed. No table-wide prune sweep exists, so
nothing is ever deleted before its sector fetch has actually run.
"""
from __future__ import annotations

import logging

from grapefruit import eodhd_client, storage


log = logging.getLogger(__name__)

_MAX_PER_RUN = 6000  # process up to 6000 symbols per run: covers the current
# universe (~5k unclassified) in a single pass; keeps the batch well under the
# EODHD daily call budget while staying within a single Cloud Run execution.


def run() -> int:
    symbols = storage.symbols_needing_sector(limit=_MAX_PER_RUN)
    if not symbols:
        log.info("no symbols need sector backfill")
        return 0

    updated = 0
    pruned = 0
    for symbol in symbols:
        try:
            fund = eodhd_client.fetch_fundamentals(symbol)
        except Exception as exc:  # noqa: BLE001 — API is flaky; skip & retry next run
            log.warning("EODHD fundamentals failed for %s: %s", symbol, exc)
            continue

        if not fund:
            # No data: leave NULL, retry on a later run.
            continue

        general = fund.get("General") or {}
        sector = general.get("Sector")
        industry = (general.get("Industry") or "").strip()

        if not sector and not industry:
            # Undetermined: leave NULL, retry on a later run.
            continue

        if industry != "Biotechnology":
            # Definitively not biotech: drop now, with its bars (FK cascade
            # removes step changes / catalysts too).
            storage.delete_asset(symbol)
            pruned += 1
            continue

        storage.update_asset_sector(symbol, sector=sector, industry=industry)
        updated += 1
        if (updated + pruned) % 50 == 0:
            log.info("classified %d (kept biotech: %d, pruned non-biotech: %d)",
                     updated + pruned, updated, pruned)

    log.info("refresh_sectors done: %d biotech kept, %d non-biotech pruned (of %d tried)",
             updated, pruned, len(symbols))
    return updated
