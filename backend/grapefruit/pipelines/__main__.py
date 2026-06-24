"""CLI dispatcher for Cloud Run Jobs.

Usage:
    python -m grapefruit.pipelines <job_name>

Each pipeline wraps its work in start_pipeline_run / finish_pipeline_run so the
UI can show 'last run' status per job. Exit code 0 on success, 1 on failure.
"""
from __future__ import annotations

import importlib
import logging
import sys
import traceback

from grapefruit import storage


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("pipelines")


KNOWN_JOBS = {
    "refresh_universe",
    "refresh_bars",
    "refresh_fundamentals",
    "detect_winners",
    "enrich_catalysts",
    "refresh_watchlist",
    "refresh_sectors",
    "refresh_upcoming_events",
    "weekly",
}


def main(argv: list[str]) -> int:
    if len(argv) != 2 or argv[1] not in KNOWN_JOBS:
        print(f"Usage: python -m grapefruit.pipelines <{ '|'.join(sorted(KNOWN_JOBS)) }>", file=sys.stderr)
        return 2

    job_name = argv[1]
    storage.init_db()
    run_id = storage.start_pipeline_run(job_name)
    log.info("starting %s (run_id=%d)", job_name, run_id)
    try:
        mod = importlib.import_module(f"grapefruit.pipelines.{job_name}")
        rows = int(mod.run())
        storage.finish_pipeline_run(run_id, rows_processed=rows)
        log.info("done %s (run_id=%d, rows=%d)", job_name, run_id, rows)
        return 0
    except Exception as exc:  # noqa: BLE001
        err = f"{type(exc).__name__}: {exc}"
        log.exception("failed %s (run_id=%d)", job_name, run_id)
        storage.finish_pipeline_run(run_id, error=f"{err}\n{traceback.format_exc()[:2000]}")
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
