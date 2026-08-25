"""Weekly orchestrator: runs the full pipeline in order.

Called by Cloud Scheduler once per week (Monday 09:00 UTC). Each step is
independent and idempotent, so re-running this on a failure resumes from
clean state.
"""
from __future__ import annotations

import logging

from grapefruit.pipelines import (
    detect_step_changes,
    enrich_catalysts,
    refresh_bars,
    refresh_sectors,
    refresh_universe,
    scan_catalysts,
    evaluate_predictions,
)


log = logging.getLogger(__name__)


def run() -> int:
    total = 0
    failures: list[str] = []
    for step in (
        refresh_universe,        # 1. Build universe (price ceiling + mcap floor)
        refresh_sectors,         # 2. Populate sector/industry; prune to Biotech-only
        refresh_bars,            # 3. Fetch 3y daily prices for BIOTECH names only
        detect_step_changes,     # 4. Find 2×+ step changes (1 day–3 months)
        enrich_catalysts,        # 5. Explain past events with Perplexity
        scan_catalysts,          # 6. Scan upcoming catalysts with Perplexity (biotech only)
        evaluate_predictions,    # 7. Review predictions whose dates have passed
    ):
        name = step.__name__.split(".")[-1]
        log.info("==> %s", name)
        try:
            rows = int(step.run() or 0)
        except Exception:
            log.exception("step %s failed; continuing", name)
            failures.append(name)
            continue
        log.info("<== %s: %d rows", name, rows)
        total += rows
    if failures:
        raise RuntimeError(f"weekly completed with failed steps: {', '.join(failures)}")
    return total
