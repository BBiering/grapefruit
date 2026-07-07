"""Tier 1: Corporate Spin-offs and Carve-outs.

Scans top market cap stocks for:
- Announced spin-offs with ex-date scheduled
- Business unit carve-outs creating new public entities
- Reverse Morris Trust transactions

Rate limit: 300 calls/week (top 300 by market cap).
"""
from __future__ import annotations

import logging

from grapefruit import catalyst, storage


log = logging.getLogger(__name__)

_MAX_SCANS_PER_RUN = 300  # Budget: 300 Perplexity calls/week for spin-offs


def run() -> int:
    """Scan top market cap stocks for Tier 1 spin-off catalysts."""
    # Get top 300 stocks by market cap (spin-offs come from larger companies)
    top_stocks = storage.top_symbols_by_market_cap(limit=_MAX_SCANS_PER_RUN)
    log.info("found %d top market cap stocks", len(top_stocks))

    if not top_stocks:
        log.warning("no stocks found; skipping Tier 1 spin-off scan")
        return 0

    log.info("scanning %d stocks for spin-offs", len(top_stocks))

    results = []
    detected_count = 0

    for i, stock in enumerate(top_stocks, start=1):
        symbol = stock["symbol"]
        name = stock.get("name")
        price = stock.get("last_close")

        if i % 50 == 0:
            log.info("progress: %d/%d scanned, %d catalysts detected", i, len(top_stocks), detected_count)

        result = catalyst.tier1_spinoff_catalyst(symbol, name, price)

        if result.get("detected"):
            detected_count += 1
            log.info("DETECTED: %s - %s (%s)", symbol, result.get("event_name"), result.get("expected_window"))

        results.append(result)

    log.info("tier1 spinoff scan complete: %d/%d catalysts detected", detected_count, len(results))

    # TODO: Implement storage.upsert_catalysts_with_tier(results, tier=1)
    return detected_count
