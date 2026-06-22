"""Weekly orchestrator: runs the full pipeline in order.

Called by Cloud Scheduler once per week (Monday 09:00 UTC). Each step is
independent and idempotent, so re-running this on a failure resumes from
clean state.
"""
from __future__ import annotations

import logging

from grapefruit.pipelines import (
    detect_winners,
    enrich_catalysts,
    refresh_bars,
    refresh_fundamentals,
    refresh_universe,
    refresh_upcoming_events,
    refresh_watchlist,
)


log = logging.getLogger(__name__)


def run() -> int:
    total = 0
    for step in (
        refresh_universe,
        refresh_fundamentals,
        refresh_bars,
        detect_winners,
        enrich_catalysts,
        refresh_watchlist,
        refresh_upcoming_events,
    ):
        name = step.__name__.split(".")[-1]
        log.info("==> %s", name)
        rows = int(step.run() or 0)
        log.info("<== %s: %d rows", name, rows)
        total += rows
    return total
