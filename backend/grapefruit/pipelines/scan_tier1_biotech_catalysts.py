"""Tier 1: Biotech/Pharma FDA and Clinical Trial Catalysts.

Deep scans biotech sector for:
- FDA PDUFA target action dates
- FDA AdCom meeting dates
- Phase 2b/3 topline data readouts
- BLA/NDA submission acceptances

Rate limit: 200 calls/week (biotech sector priority).
"""
from __future__ import annotations

import logging

from grapefruit import catalyst, storage


log = logging.getLogger(__name__)

_BIOTECH_SECTORS = ["Biotechnology", "Pharmaceuticals", "Healthcare"]
_MAX_SCANS_PER_RUN = 200  # Budget: 200 Perplexity calls/week for biotech


def run() -> int:
    """Scan biotech sector for Tier 1 FDA/clinical trial catalysts."""
    # Get biotech/pharma stocks from assets table
    biotech_symbols = storage.symbols_by_sector(_BIOTECH_SECTORS)
    log.info("found %d biotech/pharma stocks in universe", len(biotech_symbols))

    if not biotech_symbols:
        log.warning("no biotech stocks found; skipping Tier 1 biotech scan")
        return 0

    # Prioritize: never scanned or stale scans (>7 days)
    # TODO: Implement proper prioritization query in storage.py
    # For now, just take first N (optimization: check last_verified_at in forward_catalysts)
    budget = min(_MAX_SCANS_PER_RUN, len(biotech_symbols))
    targets = biotech_symbols[:budget]

    log.info("NOTE: Full scan mode - consider optimizing to skip recently scanned stocks")

    log.info("scanning %d biotech stocks (budget: %d)", len(targets), budget)

    results = []
    detected_count = 0

    for i, stock in enumerate(targets, start=1):
        symbol = stock["symbol"]
        name = stock.get("name")
        price = stock.get("last_close")

        if i % 50 == 0:
            log.info("progress: %d/%d scanned, %d catalysts detected", i, len(targets), detected_count)

        result = catalyst.tier1_biotech_catalyst(symbol, name, price)

        if result.get("detected"):
            detected_count += 1
            log.info("DETECTED: %s - %s (%s)", symbol, result.get("event_name"), result.get("expected_window"))

        results.append(result)

    # Store results (would need storage.replace_catalysts with tier support)
    log.info("tier1 biotech scan complete: %d/%d catalysts detected", detected_count, len(results))

    # TODO: Implement storage.upsert_catalysts_with_tier(results, tier=1)
    # For now, just return count
    return detected_count
