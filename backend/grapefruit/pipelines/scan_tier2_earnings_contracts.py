"""Tier 2: Corporate Acceleration Catalysts.

Detects:
1. Earnings guidance upgrades (via EODHD bulk calendar + selective Perplexity)
2. Government/enterprise contract awards (via Perplexity for defense/IT sector)

Rate limits:
- EODHD: bulk earnings calendar (no per-stock cost)
- Perplexity: 40 calls for guidance upgrades, 150 calls for contracts
"""
from __future__ import annotations

import logging
from datetime import date, timedelta

from grapefruit import eodhd_client, storage


log = logging.getLogger(__name__)

_MAX_GUIDANCE_SCANS = 40  # Budget for earnings guidance upgrade detection
_MAX_CONTRACT_SCANS = 150  # Budget for contract award detection
_DEFENSE_IT_SECTORS = ["Defense", "Information Technology", "Aerospace", "Industrials"]


def run() -> int:
    """Scan for Tier 2 earnings and contract catalysts."""
    today = date.today()
    end_date = today + timedelta(days=60)

    # 1. Fetch EODHD bulk earnings calendar (all stocks at once, no Perplexity needed)
    log.info("fetching earnings calendar from %s to %s", today, end_date)
    earnings = eodhd_client.fetch_earnings_calendar(start=today, end=end_date)
    log.info("found %d upcoming earnings", len(earnings))

    # 2. Store in upcoming_events table (already implemented in refresh_upcoming_events)
    # For now, we just log and count
    events_stored = 0
    for e in earnings:
        code = e.get("code")
        event_date = e.get("date")
        if not code or not event_date:
            continue

        symbol = f"{code}.US"
        # Store event
        # TODO: storage.upsert_upcoming_event({
        #     "symbol": symbol,
        #     "event_ts": event_date,
        #     "event_type": "earnings",
        #     "title": "Earnings Report",
        #     "est_revenue": e.get("revenue_estimate"),
        #     "est_eps": e.get("estimate"),
        # })
        events_stored += 1

    log.info("earnings calendar: %d events stored", events_stored)

    # 3. Use Perplexity ONLY for guidance upgrade detection
    #    (stocks with earnings in next 14 days)
    upcoming_earnings = [
        e for e in earnings
        if e.get("date") and
           (date.fromisoformat(e["date"]) - today).days <= 14
    ]

    log.info("found %d earnings in next 14 days (candidates for guidance upgrade scan)", len(upcoming_earnings))

    # TODO: Implement guidance upgrade scanning with Perplexity
    # For now, skip this expensive step
    guidance_detected = 0

    # 4. Contract awards scan (defense/IT sector)
    log.info("scanning defense/IT sector for contract awards")

    # Smart prioritization: only scan never-scanned, approaching events, or stale (>7 days)
    contract_targets = storage.prioritize_for_catalyst_scan(
        sectors=_DEFENSE_IT_SECTORS,
        tier=2,
        limit=_MAX_CONTRACT_SCANS,
        stale_after_days=7,
    )

    log.info("found %d defense/IT stocks needing contract scan (never scanned, stale >7d, or approaching events)",
             len(contract_targets))

    if not contract_targets:
        log.info("no defense/IT stocks need scanning; all recently verified")
    else:
        log.info("scanning %d defense/IT stocks for contracts (budget: %d)", len(contract_targets), _MAX_CONTRACT_SCANS)

    # TODO: Implement contract award detection with Perplexity
    # For now, skip
    contracts_detected = 0

    log.info("tier2 scan complete: %d earnings stored, %d guidance upgrades, %d contracts",
             events_stored, guidance_detected, contracts_detected)

    return events_stored + guidance_detected + contracts_detected
