"""Weekly orchestrator: runs the full pipeline in order.

Called by Cloud Scheduler once per week (Monday 09:00 UTC). Each step is
independent and idempotent, so re-running this on a failure resumes from
clean state.
"""
from __future__ import annotations

import logging

from grapefruit.pipelines import (
    compute_strategy_tags,
    detect_step_changes,           # UPDATED: replaces detect_winners
    detect_watchlist_moves,
    enrich_catalysts,              # UPDATED: now uses step_change_history
    refresh_bars,
    refresh_company_metrics,       # NEW: universe-wide quality metrics
    refresh_fundamentals,
    refresh_sectors,
    refresh_universe,
    refresh_upcoming_events,
    refresh_watchlist,
    scan_forward_catalysts,
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
        refresh_company_metrics,        # 3. NEW: Compute quality metrics for ALL stocks
        refresh_bars,                   # 4. Fetch price data
        detect_step_changes,            # 5. UPDATED: Find step changes (1.5x+, all tiers)
        refresh_watchlist,              # 6. Build watchlist from screeners (LEGACY - will be removed)
        detect_watchlist_moves,         # 7. Recent moves in watchlist (LEGACY - will be removed)
        refresh_sectors,                # 8. Populate sector/industry

        # NEW CATALYST DETECTION PIPELINES
        scan_tier3_structural_events,   # 9. Reverse splits + index inclusion (EODHD bulk + seasonal Perplexity)
        scan_tier2_earnings_contracts,  # 10. Earnings calendar (EODHD bulk) + contract awards (Perplexity)
        scan_tier1_biotech_catalysts,   # 11. FDA/trials for biotech sector (Perplexity)
        scan_tier1_spinoffs,            # 12. Spin-offs for top 300 market cap (Perplexity)
        scan_universe_incremental,      # 13. Rotate through 250 stocks/week (Perplexity)

        enrich_catalysts,               # 14. UPDATED: Explain step changes (250/week budget)
        refresh_upcoming_events,        # 15. Fetch earnings calendar (legacy, now covered by tier2)
        scan_forward_catalysts,         # 16. Legacy watchlist scan (keep for compatibility)
        compute_strategy_tags,          # 17. Generate strategy metadata
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
