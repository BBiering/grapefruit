"""Weekly: unified future catalyst scanner (two-step Perplexity).

For every asset in the universe:
1. Perplexity Search API retrieves ranked web results about upcoming events.
2. sonar-pro extracts a structured catalyst report from those results.

Stores results in forward_catalysts with confidence and expected impact.

Rate-limited to 40 calls/min total across search + extraction (shared bucket).
"""
from __future__ import annotations

import logging
import time

from grapefruit import catalyst, storage

log = logging.getLogger(__name__)


def run() -> int:
    """Scan every asset for future catalysts. Returns number of results stored."""
    assets = storage.load_assets_map()
    if not assets:
        log.warning("no assets; run refresh_universe first")
        return 0

    symbols = list(assets.keys())
    log.info("scanning %d stocks for future catalysts", len(symbols))

    results = []
    detected_count = 0
    start_time = time.time()

    for i, symbol in enumerate(symbols, start=1):
        meta = assets.get(symbol, {})
        name = meta.get("name") or symbol
        sector = meta.get("sector") or "Unknown"

        # Latest close from bars for the prompt.
        price = None
        try:
            df = storage.load_symbol(symbol)
            if not df.empty:
                price = float(df["close"].iloc[-1])
        except Exception:  # noqa: BLE001
            pass

        report = catalyst.scan_catalyst(
            symbol=symbol,
            name=name,
            price=price,
            sector=sector,
        )

        detected = bool(report.get("detected"))
        if detected:
            detected_count += 1

        results.append({
            "symbol": symbol,
            "detected": detected,
            "event_name": report.get("event_name"),
            "impact_type": report.get("impact_type"),
            "expected_window": report.get("event_date"),
            "strategic_summary": report.get("strategic_summary"),
            "source_url": report.get("source_url"),
            "model": "agent-fast",
            "confidence": report.get("confidence"),
            "expected_impact_pct": report.get("expected_impact_pct"),
        })

        if i % 25 == 0:
            elapsed = time.time() - start_time
            log.info("scanned %d/%d (%d detected, %.1fs elapsed)",
                     i, len(symbols), detected_count, elapsed)

    # Atomically write results.
    stored = storage.replace_forward_catalysts(results)
    elapsed = time.time() - start_time
    log.info("scan_catalysts done: %d/%d detected, %d stored (%.1fs)",
             detected_count, len(symbols), stored, elapsed)
    return stored
