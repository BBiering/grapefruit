"""Weekly orchestrator: runs the full pipeline in order.

Called by Cloud Scheduler once per week (Monday 09:00 UTC). Each step is
independent and idempotent, so re-running this on a failure resumes from
clean state.
"""
from __future__ import annotations

import logging

from grapefruit.pipelines import (
    detect_winners,
    detect_watchlist_moves,
    enrich_catalysts,
    refresh_bars,
    refresh_fundamentals,
    refresh_sectors,
    refresh_universe,
    refresh_upcoming_events,
    refresh_watchlist,
    scan_forward_catalysts,
)


log = logging.getLogger(__name__)


def run() -> int:
    total = 0
    failures: list[str] = []
    for step in (
        refresh_universe,
        refresh_fundamentals,
        refresh_bars,
        detect_winners,
        refresh_watchlist,
        detect_watchlist_moves,  # after watchlist exists, detects recent moves
        refresh_sectors,   # after winners/watchlist exist, so it scopes to them
        enrich_catalysts,
        refresh_upcoming_events,
        scan_forward_catalysts,  # after watchlist exists
    ):
        name = step.__name__.split(".")[-1]
        log.info("==> %s", name)
        try:
            rows = int(step.run() or 0)
        except Exception:  # noqa: BLE001 — isolate steps so one failure
            # doesn't discard the work of the steps that already succeeded.
            log.exception("step %s failed; continuing", name)
            failures.append(name)
            continue
        log.info("<== %s: %d rows", name, rows)
        total += rows
    if failures:
        # Surface a non-zero outcome via the raised error so the run is marked
        # 'error' in pipeline_runs, but only after every step has had a turn.
        raise RuntimeError(f"weekly completed with failed steps: {', '.join(failures)}")
    return total
