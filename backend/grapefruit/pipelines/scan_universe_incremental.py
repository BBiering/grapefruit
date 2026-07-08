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
    log.info("fetching universe for incremental catalyst scanning")

    # Smart prioritization: only scan never-scanned, approaching events, or stale (>7 days)
    # No sector filter (all sectors), no tier filter (generic scan)
    candidates = storage.prioritize_for_catalyst_scan(
        sectors=None,  # All sectors
        tier=None,     # No tier filter (generic forward_catalyst scan)
        limit=_MAX_SCANS_PER_RUN,
        stale_after_days=7,
    )

    log.info("found %d universe stocks needing scan (never scanned, stale >7d, or approaching events)",
             len(candidates))

    if not candidates:
        log.info("no stocks need scanning; entire universe recently verified")
        return 0

    log.info("scanning %d universe stocks incrementally (budget: %d)", len(candidates), _MAX_SCANS_PER_RUN)

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

    # Store results with last_verified_at timestamp (no tier for generic scans)
    stored = storage.upsert_catalysts_with_tier(results)
    log.info("incremental universe scan complete: %d/%d catalysts detected, %d stored",
             detected_count, len(results), stored)

    return detected_count
