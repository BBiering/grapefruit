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
    # Smart prioritization: only scan never-scanned, approaching events, or stale (>7 days)
    targets = storage.prioritize_for_catalyst_scan(
        sectors=_BIOTECH_SECTORS,
        tier=1,
        limit=_MAX_SCANS_PER_RUN,
        stale_after_days=7,
    )

    log.info("found %d biotech stocks needing catalyst scan (never scanned, stale >7d, or approaching events)",
             len(targets))

    if not targets:
        log.info("no biotech stocks need scanning; all recently verified")
        return 0

    log.info("scanning %d biotech stocks (budget: %d)", len(targets), _MAX_SCANS_PER_RUN)

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

    # Store results with tier metadata and last_verified_at timestamp
    stored = storage.upsert_catalysts_with_tier(results)
    log.info("tier1 biotech scan complete: %d/%d catalysts detected, %d stored",
             detected_count, len(results), stored)

    return detected_count
