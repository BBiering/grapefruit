"""Weekly: refresh the universe of tradable US common stocks from EODHD,
upsert into `assets`, and snapshot the symbol list to `app_state['universe']`.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from grapefruit import eodhd_client, storage


log = logging.getLogger(__name__)


def run() -> int:
    raw = eodhd_client.list_symbols()
    rows = [
        {
            "symbol": a["Code"],
            "name": a.get("Name"),
            "exchange": a.get("Exchange"),
            "sector": None,
            "industry": None,
            "market_cap_usd": None,
            "refreshed_at": None,  # let refresh_fundamentals fill this
        }
        for a in raw
        if a.get("Code")
        and a.get("Type") == "Common Stock"
        and "/" not in a["Code"]
        and "." not in a["Code"]
    ]
    log.info("filtered %d -> %d symbols", len(raw), len(rows))

    n = storage.upsert_assets(rows)
    symbols = sorted(r["symbol"] for r in rows)
    storage.set_app_state(
        "universe",
        {
            "symbols": symbols,
            "count": len(symbols),
            "refreshed_at": datetime.now(timezone.utc).isoformat(),
        },
    )
    return n
