"""Weekly: detect recent significant moves for watchlist symbols.

Since watchlist symbols are selected by momentum, they've often had recent
step increases. This pipeline identifies those moves (similar to detect_winners
but looking at the most recent 180 days) and stores them in `watchlist_moves`.
"""
from __future__ import annotations

import logging

import numpy as np

from grapefruit import detector, storage


log = logging.getLogger(__name__)


def run() -> int:
    """Detect recent step increases (past 180 days) for current watchlist symbols."""
    watchlist = storage.watchlist_symbols()
    if not watchlist:
        log.warning("watchlist is empty; run refresh_watchlist first")
        storage.replace_watchlist_moves([])
        return 0

    symbols = [w["symbol"] for w in watchlist]

    moves: list[dict] = []
    for symbol in symbols:
        df = storage.load_symbol(symbol)
        if len(df) < 2:
            continue

        # Look at the most recent 180 trading days (roughly 6-9 months)
        df_recent = df.tail(180) if len(df) > 180 else df
        closes = df_recent["close"].to_numpy(dtype=float)
        dates = df_recent["ts"].to_numpy()

        # Use a relaxed detector: min 2x, max 14 days, no retention filter
        # (we just want to highlight the recent move that drove momentum)
        winners = detector.detect_winners(
            symbol,
            closes,
            dates,
            min_multiplier=2.0,
            max_multiplier=50.0,
            max_days=14,
            post_peak_retention_min=0.0,  # no retention filter
            breakout_vs_prior_high_min=1.0,  # no breakout filter
            min_bars=0,  # no data quality filter (watchlist already vetted)
            max_trough_price=1e9,  # no price filter
        )

        # Keep only the most recent move (if any)
        if winners:
            latest = max(winners, key=lambda w: w.end_ts)
            moves.append(
                {
                    "symbol": symbol,
                    "start_ts": latest.start_ts,
                    "end_ts": latest.end_ts,
                    "trough_price": latest.trough_price,
                    "peak_price": latest.peak_price,
                    "multiplier": latest.multiplier,
                    "days_to_peak": latest.days_to_peak,
                }
            )

    n = storage.replace_watchlist_moves(moves)
    log.info("watchlist_moves: %d symbols with recent moves", n)
    return n
