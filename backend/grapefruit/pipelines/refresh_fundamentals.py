"""Weekly: fill name / sector / industry / market_cap_usd via EODHD's bulk
extended endpoint (one HTTP call returns the whole US exchange).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from grapefruit import eodhd_client, storage


log = logging.getLogger(__name__)


def run() -> int:
    rows_raw = eodhd_client.fetch_bulk_extended()
    if not rows_raw:
        log.warning("EODHD returned no bulk rows")
        return 0

    now = datetime.now(timezone.utc)
    rows: list[dict] = []
    for r in rows_raw:
        code = r.get("code") or r.get("Code")
        if not code:
            continue
        mc = r.get("MarketCapitalization") or r.get("market_capitalization")
        rows.append(
            {
                "symbol": code,
                "name": r.get("name") or r.get("Name"),
                "exchange": r.get("exchange_short_name") or r.get("Exchange"),
                "sector": r.get("sector") or r.get("Sector"),
                "industry": r.get("industry") or r.get("Industry"),
                "market_cap_usd": float(mc) if isinstance(mc, (int, float)) and mc else None,
                "refreshed_at": now,
            }
        )
    n = storage.upsert_assets(rows)
    log.info("upserted fundamentals for %d symbols", n)
    return n
