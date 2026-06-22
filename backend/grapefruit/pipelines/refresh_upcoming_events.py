"""Weekly: pull the next ~60 days of US earnings dates from EODHD and stash
them in `upcoming_events`. Phase-3 trial results need a separate data source
(future Part 2 work); this pipeline only does earnings for now.
"""
from __future__ import annotations

import logging
from datetime import date, timedelta

from grapefruit import eodhd_client, storage


log = logging.getLogger(__name__)


def run() -> int:
    today = date.today()
    end = today + timedelta(days=60)
    rows_raw = eodhd_client.fetch_earnings_calendar(today, end)
    rows: list[dict] = []
    for r in rows_raw:
        sym = (r.get("code") or "").split(".")[0]
        ts = r.get("report_date") or r.get("date")
        if not sym or not ts:
            continue
        rows.append(
            {
                "symbol": sym,
                "event_ts": ts,
                "event_type": "earnings",
                "title": r.get("currency"),
                "source": "EODHD",
                "source_url": None,
                "est_revenue": _f(r.get("revenue_estimate")),
                "est_eps": _f(r.get("estimate")),
            }
        )
    n = storage.upsert_upcoming_events(rows)
    log.info("upserted %d upcoming earnings events", n)
    return n


def _f(v) -> float | None:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None
