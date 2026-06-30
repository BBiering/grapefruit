"""Weekly: for each watchlist symbol, ask Perplexity sonar-pro for an imminent
(next 1–90 days) forward-looking catalyst, and store the result in
`forward_catalysts`. Bounded to ~TOP_N Perplexity calls per run.
"""
from __future__ import annotations

import logging

from grapefruit import catalyst, storage


log = logging.getLogger(__name__)


def run() -> int:
    targets = storage.watchlist_symbols()
    if not targets:
        log.warning("watchlist is empty; run refresh_watchlist first")
        storage.replace_forward_catalysts([])
        return 0

    rows: list[dict] = []
    detected = 0
    for i, t in enumerate(targets, start=1):
        result = catalyst.forward_catalyst(t["symbol"], t.get("name"), t.get("last_close"))
        if result.get("error") == "no_key":
            log.warning("PERPLEXITY_API_KEY not set; aborting forward scan")
            break
        if result.get("error"):
            log.warning("forward scan error for %s: %s", t["symbol"], result["error"])
            # still record a row so the UI shows we looked (detected=false)
        if result.get("detected"):
            detected += 1
        rows.append(result)
        if i % 10 == 0:
            log.info("scanned %d/%d (%d catalysts so far)", i, len(targets), detected)

    n = storage.replace_forward_catalysts(rows)
    log.info("forward_catalysts: %d rows, %d with an imminent catalyst", n, detected)
    return n
