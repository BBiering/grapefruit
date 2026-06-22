"""Weekly: scan every symbol's cached bars and upsert detected steep-rise
events into `winners`.
"""
from __future__ import annotations

import logging

from grapefruit import storage
from grapefruit.detector import detect_winners


log = logging.getLogger(__name__)


def run() -> int:
    symbols = storage.symbols_with_bars()
    total = 0
    for i, symbol in enumerate(symbols, start=1):
        df = storage.load_symbol(symbol)
        if len(df) < 2:
            continue
        closes = df["close"].to_numpy(dtype=float)
        dates = df["ts"].to_numpy()
        winners = detect_winners(symbol, closes, dates)
        if not winners:
            continue
        meta = storage.load_asset(symbol) or {}
        for w in winners:
            storage.upsert_winner(
                {
                    "symbol": w.symbol,
                    "start_ts": w.start_ts,
                    "end_ts": w.end_ts,
                    "days_to_peak": w.days_to_peak,
                    "trough_price": w.trough_price,
                    "peak_price": w.peak_price,
                    "multiplier": w.multiplier,
                    "post_peak_retention": w.post_peak_retention,
                    "breakout_ratio": w.breakout_ratio,
                    "market_cap_usd_at_peak": meta.get("market_cap_usd"),
                    "sector": meta.get("sector"),
                    "industry": meta.get("industry"),
                    "status": w.status,
                }
            )
            total += 1
        if i % 500 == 0:
            log.info("scanned %d/%d symbols, %d winners so far", i, len(symbols), total)
    log.info("detect_winners done: %d winners across %d symbols", total, len(symbols))
    return total
