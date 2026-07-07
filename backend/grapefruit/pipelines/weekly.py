"""Weekly orchestrator: runs the full pipeline in order.

Called by Cloud Scheduler once per week (Monday 09:00 UTC). Each step is
independent and idempotent, so re-running this on a failure resumes from
clean state.
"""
from __future__ import annotations

import logging

from grapefruit.pipelines import (
    compute_strategy_tags,
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
        refresh_universe,            # 1. Build universe (with risk flag exclusions)
        refresh_fundamentals,         # 2. Fetch financials
        refresh_bars,                 # 3. Fetch price data
        detect_winners,               # 4. Find steep-rise events
        refresh_watchlist,            # 5. Build watchlist from screeners
        detect_watchlist_moves,       # 6. Recent moves in watchlist
        refresh_sectors,              # 7. Populate sector/industry

        # NEW CATALYST DETECTION PIPELINES
        scan_tier3_structural_events,  # 8. Reverse splits + index inclusion (EODHD bulk + seasonal Perplexity)
        scan_tier2_earnings_contracts, # 9. Earnings calendar (EODHD bulk) + contract awards (Perplexity)
        scan_tier1_biotech_catalysts,  # 10. FDA/trials for biotech sector (Perplexity)
        scan_tier1_spinoffs,           # 11. Spin-offs for top 300 market cap (Perplexity)
        scan_universe_incremental,     # 12. Rotate through 250 stocks/week (Perplexity)

        enrich_catalysts,              # 13. Explain past winners
        refresh_upcoming_events,       # 14. Fetch earnings calendar (legacy, now covered by tier2)
        scan_forward_catalysts,        # 15. Legacy watchlist scan (keep for compatibility)
        compute_strategy_tags,         # 16. Generate strategy metadata
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
