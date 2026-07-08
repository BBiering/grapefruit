"""Tier 3: Structural Maintenance Events (volatile/risky).

Detects:
1. Reverse stock splits (RISK FLAG - exclude from universe)
2. Index inclusion announcements (seasonal - Russell 2000, S&P SmallCap 600)

Data sources:
- EODHD splits calendar (bulk)
- Perplexity web search (seasonal for index rebalancing)
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone

from grapefruit import eodhd_client, storage


log = logging.getLogger(__name__)


def parse_split_ratio(ratio: str) -> tuple[int, int]:
    """Parse split ratio string like '2:1' or '1:5' into (new, old) shares.

    Examples:
        '2:1' -> (2, 1) = forward split (1 share becomes 2)
        '1:5' -> (1, 5) = reverse split (5 shares become 1)
    """
    parts = ratio.replace(" ", "").split(":")
    if len(parts) != 2:
        raise ValueError(f"Invalid split ratio format: {ratio}")
    return int(parts[0]), int(parts[1])


def is_reverse_split(ratio: str) -> bool:
    """Check if ratio represents a reverse split (consolidation)."""
    new_shares, old_shares = parse_split_ratio(ratio)
    return new_shares < old_shares


def is_rebalancing_season() -> bool:
    """Check if we're in Russell/S&P rebalancing season (May-June, Nov-Dec)."""
    month = datetime.now(timezone.utc).month
    return month in (5, 6, 11, 12)


def run() -> int:
    """Scan for Tier 3 structural events: reverse splits + index inclusions."""
    today = date.today()
    end_date = today + timedelta(days=90)

    # 1. Fetch upcoming splits from EODHD
    log.info("fetching splits calendar from %s to %s", today, end_date)
    splits = eodhd_client.fetch_splits_calendar(start=today, end=end_date)
    log.info("found %d upcoming splits", len(splits))

    # 2. Identify reverse splits (RISK FLAG)
    reverse_splits = []
    forward_splits = []

    for split in splits:
        code = split.get("code")
        split_date = split.get("date") or split.get("split_date")

        # Handle two API formats: "split" ratio string OR "old_shares"/"new_shares" numbers
        ratio = split.get("split")
        old_shares = split.get("old_shares")
        new_shares = split.get("new_shares")

        if not code or not split_date:
            log.warning("incomplete split data (missing code or date): %s", split)
            continue

        # Construct ratio from old_shares/new_shares if ratio not provided
        if not ratio and old_shares and new_shares:
            ratio = f"{new_shares}:{old_shares}"

        if not ratio:
            log.warning("incomplete split data (no ratio): %s", split)
            continue

        symbol = f"{code}.US"

        try:
            if is_reverse_split(ratio):
                reverse_splits.append({
                    "symbol": symbol,
                    "flag_type": "reverse_split",
                    "flag_date": today,
                    "scheduled_date": split_date,
                    "split_ratio": ratio,
                    "description": f"Reverse split {ratio} scheduled for {split_date} - distress signal",
                })
            else:
                forward_splits.append((symbol, ratio, split_date))
        except ValueError as exc:
            log.warning("failed to parse split ratio for %s: %s", symbol, exc)
            continue

    log.info("identified %d reverse splits (risk flags), %d forward splits (benign)",
             len(reverse_splits), len(forward_splits))

    # 3. Store risk flags for reverse splits
    if reverse_splits:
        stored = storage.upsert_risk_flags(reverse_splits)
        log.info("stored %d reverse split risk flags", stored)

    # 4. Seasonal index inclusion scan (June/December only)
    # TODO: Implement Perplexity scan for Russell 2000 / S&P SmallCap 600 rebalancing
    # This would use catalyst.py with a specialized prompt for index inclusion
    # For now, we skip this as it's seasonal and requires manual review

    if is_rebalancing_season():
        log.info("in rebalancing season (month=%d) - index inclusion scan would run here",
                 datetime.now(timezone.utc).month)
        # Future: scan top 300 small-caps for index inclusion candidates

    return len(reverse_splits)
