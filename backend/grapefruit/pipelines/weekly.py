"""Weekly orchestrator: runs the full pipeline in order.

Called by Cloud Scheduler once per week (Monday 09:00 UTC). Each step is
independent and idempotent, so re-running this on a failure resumes from
clean state.
"""
from __future__ import annotations

import logging

from grapefruit.pipelines import (
    compute_strategy_tags,
    detect_step_changes,           # Find step changes (1.5x+, all tiers)
    enrich_catalysts,              # Explain step changes with Perplexity
    refresh_bars,
    refresh_company_metrics,       # Universe-wide quality metrics
    refresh_fundamentals,
    refresh_sectors,
    refresh_universe,
    scan_tier1_biotech_catalysts,
    scan_tier1_spinoffs,
    scan_tier2_earnings_contracts,
    scan_tier3_structural_events,
    scan_universe_incremental,
)


log = logging.getLogger(__name__)


def run() -> int:
    total = 0
    failures: list[str] = []
    for step in (
        refresh_universe,               # 1. Build universe (with risk flag exclusions)
        refresh_fundamentals,           # 2. Fetch financials
        refresh_company_metrics,        # 3. Compute quality metrics for ALL stocks
        refresh_bars,                   # 4. Fetch price data
        detect_step_changes,            # 5. Find step changes (1.5x+, all tiers)
        refresh_sectors,                # 6. Populate sector/industry

        # CATALYST DETECTION PIPELINES
        scan_tier3_structural_events,   # 7. Reverse splits + index inclusion
        scan_tier2_earnings_contracts,  # 8. Earnings calendar + contract awards
        scan_tier1_biotech_catalysts,   # 9. FDA/trials for biotech sector
        scan_tier1_spinoffs,            # 10. Spin-offs for top 300 market cap
        scan_universe_incremental,      # 11. Rotate through 250 stocks/week

        enrich_catalysts,               # 12. Explain step changes (250/week budget)
        compute_strategy_tags,          # 13. Generate strategy metadata
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
