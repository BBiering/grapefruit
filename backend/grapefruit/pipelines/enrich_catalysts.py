"""Weekly: for each `step_change_history` row without a catalyst, call Perplexity
and upsert into `step_change_catalysts`.

Prioritizes by tier (major first) → recency → never-explained.
Budget: 250 explanations per week to manage API costs (~$2.50-5/week).
"""
from __future__ import annotations

import logging

from grapefruit import storage
from grapefruit.catalyst import explain_move


log = logging.getLogger(__name__)


def run(limit: int = 250) -> int:
    """Fetch catalyst explanations for unexplained step changes.

    Args:
        limit: Maximum number of explanations to fetch per run (default 250/week)

    Returns:
        Number of catalysts fetched
    """
    # Get unexplained step changes, prioritized by tier → recency
    pending = storage.load_unexplained_step_changes(limit=limit)

    if not pending:
        log.info("No unexplained step changes found")
        return 0

    log.info(f"Found {len(pending)} unexplained step changes to enrich")

    fetched = 0
    for i, event in enumerate(pending, start=1):
        # Load asset metadata for name
        asset = storage.load_asset(event["symbol"]) or {}

        result = explain_move(
            symbol=event["symbol"],
            name=asset.get("name"),
            around=event["end_ts"],
            trough_price=event.get("trough_price"),
            peak_price=event.get("peak_price"),
            start=event["start_ts"],
        )

        if result.get("error"):
            log.warning(
                "perplexity error for %s/%s (tier=%s): %s",
                event["symbol"], event["end_ts"], event.get("tier"), result["error"]
            )
            continue

        storage.upsert_step_change_catalyst(
            {
                "step_change_id": event["id"],
                "headline": result.get("headline") or None,
                "summary": result.get("summary") or None,
                "spike_explanation": result.get("spike_explanation") or None,
                "was_foreseeable": result.get("was_foreseeable"),
                "foreseeable_evidence": result.get("foreseeable_evidence") or None,
                "perplexity_citations": result.get("citations"),
                "model": "sonar-pro",
            }
        )

        fetched += 1

        if i % 25 == 0:
            log.info(
                "processed %d/%d (%d fetched, tier breakdown: major=%d, moderate=%d, minor=%d)",
                i, len(pending), fetched,
                sum(1 for e in pending[:i] if e.get("tier") == "major"),
                sum(1 for e in pending[:i] if e.get("tier") == "moderate"),
                sum(1 for e in pending[:i] if e.get("tier") == "minor"),
            )

    log.info("enrich_catalysts done: %d/%d fetched", fetched, len(pending))

    # Log tier breakdown
    tier_counts = {}
    for event in pending[:fetched]:
        tier = event.get("tier", "unknown")
        tier_counts[tier] = tier_counts.get(tier, 0) + 1

    log.info("  Tier breakdown: %s", tier_counts)

    return fetched


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    run()


if __name__ == "__main__":
    main()
