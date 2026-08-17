"""Weekly: scan every symbol's cached bars and detect 5x+ step changes.

Finds every event where price rose >= 5x in <= 10 consecutive bars, the peak
held >= 70% for 30 calendar days, and the peak was >= 1.5x the 180-day high
before the trough. Stores in step_change_history with tier='major'.
"""
from __future__ import annotations

import logging

from grapefruit import storage
from grapefruit.detector import detect_winners

log = logging.getLogger(__name__)


def run() -> int:
    """Detect 5x+ step changes for all symbols with bars data."""
    symbols = storage.symbols_with_bars()
    total = 0

    log.info("scanning %d symbols for 5x+ step changes", len(symbols))

    for i, symbol in enumerate(symbols, start=1):
        df = storage.load_symbol(symbol)
        if len(df) < 2:
            continue

        closes = df["close"].to_numpy(dtype=float)
        dates = df["ts"].to_numpy()

        detected = detect_winners(
            symbol,
            closes,
            dates,
            min_multiplier=5.0,
            max_days=10,
            post_peak_retention_min=0.70,
            breakout_vs_prior_high_min=1.5,
        )

        if not detected:
            continue

        meta = storage.load_asset(symbol) or {}

        for event in detected:
            storage.upsert_step_change(
                {
                    "symbol": event.symbol,
                    "start_ts": event.start_ts,
                    "end_ts": event.end_ts,
                    "days_to_peak": event.days_to_peak,
                    "trough_price": event.trough_price,
                    "peak_price": event.peak_price,
                    "multiplier": event.multiplier,
                    "post_peak_retention": event.post_peak_retention,
                    "breakout_ratio": event.breakout_ratio,
                    "market_cap_usd_at_peak": meta.get("market_cap_usd"),
                    "status": event.status,
                    "tier": "major",
                }
            )
            total += 1

        if i % 500 == 0:
            log.info("scanned %d/%d symbols, %d events so far", i, len(symbols), total)

    log.info("detect_step_changes done: %d events across %d symbols", total, len(symbols))
    return total
