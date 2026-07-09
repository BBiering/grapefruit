"""Compute strategy alignment tags for watchlist stocks.

Runs after watchlist + forward_catalysts are populated.
Updates the strategy_tag column based on quality/catalyst alignment.
"""
from __future__ import annotations

import logging

from grapefruit import storage, strategy_alignment


log = logging.getLogger(__name__)


def run() -> int:
    """Compute and update strategy tags for all watchlist stocks."""
    # Fetch watchlist with catalyst data
    with storage._cur(row_factory=storage.dict_row) as cur:
        cur.execute(
            """
            SELECT w.symbol, w.quality_score,
                   fc.detected as catalyst_detected
            FROM watchlist w
            LEFT JOIN forward_catalysts fc ON fc.symbol = w.symbol
            """
        )
        rows = [dict(r) for r in cur.fetchall()]

    if not rows:
        log.warning("watchlist is empty; nothing to tag")
        return 0

    # Compute tags
    updates = []
    tag_counts = {"Buy Manually": 0, "Watchlist": 0, "Pass": 0}
    for r in rows:
        tag = strategy_alignment.compute_strategy_tag(
            quality_score=r["quality_score"],
            catalyst_detected=r["catalyst_detected"],
        )
        updates.append((tag, r["symbol"]))
        tag_counts[tag] += 1

    # Update database
    with storage._conn() as con:
        with con.cursor() as cur:
            cur.executemany(
                "UPDATE watchlist SET strategy_tag = %s WHERE symbol = %s",
                updates,
            )

    log.info("strategy tags: %d Buy Manually, %d Watchlist, %d Pass",
             tag_counts["Buy Manually"], tag_counts["Watchlist"], tag_counts["Pass"])
    return len(updates)
