"""Weekly: scan every symbol's cached bars and detect ALL step changes (1.5x+).

Replaces detect_winners.py with universe-wide coverage at relaxed thresholds.

Tier classification:
- major: 5x+ multiplier (original winners)
- moderate: 2-5x multiplier (significant moves)
- minor: 1.5-2x multiplier (notable moves)

Stores in step_change_history table instead of winners table.
"""
from __future__ import annotations

import logging

from grapefruit import storage
from grapefruit.detector import detect_winners

log = logging.getLogger(__name__)


def classify_tier(multiplier: float) -> str:
    """Classify step change tier based on multiplier."""
    if multiplier >= 5.0:
        return "major"
    elif multiplier >= 2.0:
        return "moderate"
    elif multiplier >= 1.5:
        return "minor"
    else:
        return "minor"  # Shouldn't happen due to min_multiplier


def run(
    min_multiplier: float = 1.5,
    max_days: int = 7,
    post_peak_retention_min: float = 0.70,
    breakout_vs_prior_high_min: float = 1.5,
) -> int:
    """Detect step changes for all symbols with relaxed thresholds.

    Args:
        min_multiplier: Minimum multiplier to detect (1.5x = minor tier threshold)
        max_days: Maximum days from trough to peak
        post_peak_retention_min: Minimum retention ratio after peak
        breakout_vs_prior_high_min: Minimum breakout ratio vs 180d high

    Returns:
        Number of step changes detected
    """
    symbols = storage.symbols_with_bars()
    total = 0
    by_tier = {"major": 0, "moderate": 0, "minor": 0}

    log.info(f"Scanning {len(symbols)} symbols for step changes (min {min_multiplier}x)")

    for i, symbol in enumerate(symbols, start=1):
        df = storage.load_symbol(symbol)
        if len(df) < 2:
            continue

        closes = df["close"].to_numpy(dtype=float)
        dates = df["ts"].to_numpy()

        # Use detect_winners with relaxed min_multiplier threshold
        detected = detect_winners(
            symbol,
            closes,
            dates,
            min_multiplier=min_multiplier,
            max_days=max_days,
            post_peak_retention_min=post_peak_retention_min,
            breakout_vs_prior_high_min=breakout_vs_prior_high_min,
        )

        if not detected:
            continue

        meta = storage.load_asset(symbol) or {}

        for event in detected:
            tier = classify_tier(event.multiplier)

            step_change_id = storage.upsert_step_change(
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
                    "tier": tier,
                }
            )

            total += 1
            by_tier[tier] += 1

        if i % 500 == 0:
            log.info(
                "scanned %d/%d symbols, %d step changes so far (major: %d, moderate: %d, minor: %d)",
                i, len(symbols), total, by_tier["major"], by_tier["moderate"], by_tier["minor"]
            )

    log.info(
        "detect_step_changes done: %d step changes across %d symbols",
        total, len(symbols)
    )
    log.info(
        "  Breakdown: major=%d (5x+), moderate=%d (2-5x), minor=%d (1.5-2x)",
        by_tier["major"], by_tier["moderate"], by_tier["minor"]
    )

    return total


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    run()


if __name__ == "__main__":
    main()
