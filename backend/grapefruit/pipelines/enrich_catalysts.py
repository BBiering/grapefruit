"""Weekly: for each `winners` row without a catalyst, call Perplexity and
upsert into `winner_catalysts`. Respects the PERPLEXITY_BUCKET rate limit.
"""
from __future__ import annotations

import logging

from grapefruit import storage
from grapefruit.catalyst import explain_move


log = logging.getLogger(__name__)


def run() -> int:
    pending = storage.winners_without_catalyst(limit=200)
    if not pending:
        return 0
    fetched = 0
    for i, w in enumerate(pending, start=1):
        result = explain_move(
            symbol=w["symbol"],
            name=w.get("name"),
            around=w["end_ts"],
            trough_price=w.get("trough_price"),
            peak_price=w.get("peak_price"),
            start=w["start_ts"],
        )
        if result.get("error"):
            log.warning("perplexity error for %s/%s: %s", w["symbol"], w["end_ts"], result["error"])
            continue
        storage.upsert_winner_catalyst(
            {
                "winner_id": w["id"],
                "headline": result.get("headline") or None,
                "summary": result.get("summary") or None,
                "spike_explanation": result.get("spike_explanation") or None,
                "was_foreseeable": result.get("was_foreseeable"),
                "foreseeable_evidence": result.get("foreseeable_evidence") or None,
                "perplexity_citations": result.get("citations"),
            }
        )
        fetched += 1
        if i % 25 == 0:
            log.info("processed %d/%d (%d fetched)", i, len(pending), fetched)
    log.info("enrich_catalysts done: %d/%d fetched", fetched, len(pending))
    return fetched
