"""Weekly: unified future catalyst scanner.

Iterates all assets and asks Perplexity sonar-pro for upcoming catalysts
in the next 3 months. Stores results in forward_catalysts with confidence
and expected impact percentage.

Rate-limited to ~30 calls/min to stay within Perplexity API limits.
Budget: scans every symbol in the universe each week (~432 stocks).
"""
from __future__ import annotations

import logging
import time

from grapefruit import catalyst, storage

log = logging.getLogger(__name__)

# Prompt for the unified scan
_PROMPT = (
    "You are an institutional research analyst. For the European stock {label} "
    "(sector: {sector}, current price: {price}), identify SPECIFIC upcoming "
    "catalyst events in the next 3 months that could cause a significant price "
    "move. Search regulatory filings, exchange announcements, corporate calendars, "
    "clinical trial registries, and financial news.\n\n"
    "Return a JSON object with exactly these keys:\n"
    "{{\n"
    '  "catalyst_detected": true or false,\n'
    '  "event_name": "specific event name or empty string",\n'
    '  "event_date": "YYYY-MM-DD or empty if not known",\n'
    '  "impact_type": "Earnings | Regulatory | Clinical Trial | Spin-off | Contract | Other",\n'
    '  "expected_impact_pct": number (estimated price change %, e.g. 15.0 for +15%),\n'
    '  "confidence": "high" | "medium" | "low",\n'
    '  "strategic_summary": "1-2 sentences on the catalyst and potential impact",\n'
    '  "source_url": "URL of official source or empty"\n'
    "}}\n\n"
    "Only return detected=true if you found a specific, scheduled future event "
    "with a date or narrow window."
)


def run() -> int:
    """Scan every asset for future catalysts. Returns number of catalysts detected."""
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

        # Get latest price from bars for the prompt
        price_str = "unknown"
        try:
            df = storage.load_symbol(symbol)
            if not df.empty:
                last_close = float(df["close"].iloc[-1])
                price_str = f"${last_close:.2f}"
        except Exception:
            pass

        label = f"{symbol} ({name})"
        prompt = _PROMPT.format(label=label, sector=sector, price=price_str)

        try:
            result = catalyst.query_perplexity(prompt)
        except Exception as exc:
            log.warning("perplexity failed for %s: %s", symbol, exc)
            results.append({
                "symbol": symbol,
                "detected": False,
                "event_name": None,
                "impact_type": None,
                "expected_window": None,
                "strategic_summary": None,
                "source_url": None,
                "model": "sonar-pro",
                "confidence": None,
                "expected_impact_pct": None,
            })
            continue

        detected = bool(result.get("catalyst_detected"))
        if detected:
            detected_count += 1

        results.append({
            "symbol": symbol,
            "detected": detected,
            "event_name": result.get("event_name") or None,
            "impact_type": result.get("impact_type") or None,
            "expected_window": result.get("event_date") or None,
            "strategic_summary": result.get("strategic_summary") or None,
            "source_url": result.get("source_url") or None,
            "model": "sonar-pro",
            "confidence": result.get("confidence") or None,
            "expected_impact_pct": result.get("expected_impact_pct"),
        })

        # Rate limit: ~30 calls/min = 1 call per 2 seconds
        if i % 5 == 0:
            time.sleep(0.5)

        if i % 50 == 0:
            elapsed = time.time() - start_time
            log.info("scanned %d/%d (%d detected, %.1fs elapsed)",
                     i, len(symbols), detected_count, elapsed)

    # Atomically write results
    stored = storage.replace_forward_catalysts(results)
    elapsed = time.time() - start_time
    log.info("scan_catalysts done: %d/%d detected, %d stored (%.1fs)",
             detected_count, len(symbols), stored, elapsed)
    return stored
