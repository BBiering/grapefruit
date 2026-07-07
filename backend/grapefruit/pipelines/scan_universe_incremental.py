"""Incremental Universe Catalyst Scanning.

Rotates through full 1,876 universe at 250 stocks/week (8-week cycle).

Prioritization:
1. Never scanned (last_verified_at IS NULL)
2. Approaching event dates (event_date within 14 days, needs re-verification)
3. Stale scans (last_verified_at < 7 days ago)

Rate limit: 250 Perplexity calls/week.
"""
from __future__ import annotations

import logging

from grapefruit import catalyst, storage


log = logging.getLogger(__name__)

_MAX_SCANS_PER_RUN = 250  # Budget: 250 stocks/week = full universe every 8 weeks


def run() -> int:
    """Incrementally scan universe for generic catalysts with prioritization."""
    # Get prioritized candidates from storage
    # TODO: Implement storage.prioritize_universe_for_scanning()
    # For now, use a simple approach: get all assets, take first 250

    log.info("fetching universe for incremental catalyst scanning")

    # Placeholder: just get first 250 symbols from assets
    # In production, this would use the prioritization query from the plan
    with storage._cur(row_factory=storage.dict_row) as cur:
        cur.execute("""
            SELECT a.symbol, a.name, a.last_close
            FROM assets a
            ORDER BY a.symbol
            LIMIT %s
        """, [_MAX_SCANS_PER_RUN])
        candidates = [dict(r) for r in cur.fetchall()]

    log.info("scanning %d universe stocks incrementally", len(candidates))

    results = []
    detected_count = 0

    for i, stock in enumerate(candidates, start=1):
        symbol = stock["symbol"]
        name = stock.get("name")
        price = stock.get("last_close")

        if i % 50 == 0:
            log.info("progress: %d/%d scanned, %d catalysts detected", i, len(candidates), detected_count)

        # Use generic forward_catalyst scan (existing function)
        result = catalyst.forward_catalyst(symbol, name, price)

        if result.get("detected"):
            detected_count += 1
            log.info("DETECTED: %s - %s", symbol, result.get("event_name"))

        results.append(result)

    log.info("incremental universe scan complete: %d/%d catalysts detected", detected_count, len(results))

    # TODO: Implement storage.upsert_catalysts with tier=None for generic scans
    return detected_count
