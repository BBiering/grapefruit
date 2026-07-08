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

_MAX_SCANS_PER_RUN = 150  # Budget: 150 per run to avoid timeout (300 weekly across 2 runs)


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

    detected_count = 0

    for i, stock in enumerate(targets, start=1):
        symbol = stock["symbol"]
        name = stock.get("name")
        price = stock.get("last_close")

        result = catalyst.tier1_spinoff_catalyst(symbol, name, price)

        if result.get("detected"):
            detected_count += 1
            log.info("DETECTED: %s - %s (%s)", symbol, result.get("event_name"), result.get("expected_window"))

        # Store immediately after each fetch with retry
        for retry in range(3):
            try:
                stored = storage.upsert_catalysts_with_tier([result])
                if i % 10 == 0:  # Log progress every 10 stocks
                    log.info("progress: %d/%d scanned, %d catalysts detected",
                             i, len(targets), detected_count)
                break
            except Exception as exc:  # noqa: BLE001
                log.warning("storage failed for %s (attempt %d/3): %s", symbol, retry + 1, exc)
                if retry < 2:
                    import time
                    time.sleep(2 ** retry)

    log.info("tier1 spinoff scan complete: %d/%d catalysts detected", detected_count, len(targets))

    return detected_count
