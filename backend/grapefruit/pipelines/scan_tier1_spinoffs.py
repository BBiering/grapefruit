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
    # Smart prioritization: only scan never-scanned, approaching events, or stale (>7 days)
    # No sector filter (spin-offs can come from any sector, but prioritize by market cap)
    targets = storage.prioritize_for_catalyst_scan(
        sectors=None,  # All sectors
        tier=1,
        limit=_MAX_SCANS_PER_RUN,
        stale_after_days=7,
    )

    log.info("found %d stocks needing spin-off scan (never scanned, stale >7d, or approaching events)",
             len(targets))

    if not targets:
        log.info("no stocks need scanning; all recently verified")
        return 0

    log.info("scanning %d stocks for spin-offs (budget: %d)", len(targets), _MAX_SCANS_PER_RUN)

    results = []
    detected_count = 0
    batch_size = 50  # Store results every 50 stocks to avoid losing progress on timeout

    for i, stock in enumerate(targets, start=1):
        symbol = stock["symbol"]
        name = stock.get("name")
        price = stock.get("last_close")

        result = catalyst.tier1_spinoff_catalyst(symbol, name, price)

        if result.get("detected"):
            detected_count += 1
            log.info("DETECTED: %s - %s (%s)", symbol, result.get("event_name"), result.get("expected_window"))

        results.append(result)

        # Store incrementally every batch_size stocks to avoid losing progress on timeout
        if i % batch_size == 0:
            for retry in range(3):
                try:
                    stored = storage.upsert_catalysts_with_tier(results)
                    log.info("progress: %d/%d scanned, %d catalysts detected, %d stored (batch)",
                             i, len(targets), detected_count, stored)
                    results = []
                    break
                except Exception as exc:  # noqa: BLE001
                    log.warning("batch storage failed (attempt %d/3): %s", retry + 1, exc)
                    if retry < 2:
                        import time
                        time.sleep(2 ** retry)

    # Store final batch with retry
    if results:
        for retry in range(3):
            try:
                stored = storage.upsert_catalysts_with_tier(results)
                log.info("stored final batch: %d results", stored)
                break
            except Exception as exc:  # noqa: BLE001
                log.warning("final batch storage failed (attempt %d/3): %s", retry + 1, exc)
                if retry < 2:
                    import time
                    time.sleep(2 ** retry)

    log.info("tier1 spinoff scan complete: %d/%d catalysts detected", detected_count, len(targets))

    return detected_count
