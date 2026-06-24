"""Weekly: refresh the Part 2 watchlist.

Stub strategy: the universe is already small/mid-cap common stocks ($300M-$10B USD)
across US + EU exchanges, so the watchlist is currently the full universe with
a latest close attached. Atomically replaces the table. (The old absolute
last-close <= $20 rule was dropped: bars are now in mixed local currencies
— USD, GBp, EUR, SEK, DKK, NOK — so a flat price threshold is meaningless.)
Future Part 2 work will weight by the catalysts found in Part 1.
"""
from __future__ import annotations

import logging

from grapefruit import storage


log = logging.getLogger(__name__)


def run() -> int:
    with storage._cur() as cur:
        cur.execute(
            """
            WITH latest AS (
                SELECT b.symbol, b.close, b.ts
                FROM bars b
                JOIN (SELECT symbol, MAX(ts) AS mx FROM bars GROUP BY symbol) m
                  ON m.symbol = b.symbol AND m.mx = b.ts
            )
            SELECT a.symbol, l.close AS last_close, a.market_cap_usd,
                   a.sector, a.industry
            FROM assets a
            JOIN latest l ON l.symbol = a.symbol
            WHERE l.close IS NOT NULL AND l.close > 0
              AND a.market_cap_usd IS NOT NULL
              AND a.market_cap_usd BETWEEN 300e6 AND 10e9
            ORDER BY a.market_cap_usd DESC
            """
        )
        rows = [
            {
                "symbol": r[0],
                "last_close": float(r[1]) if r[1] is not None else None,
                "market_cap_usd": float(r[2]) if r[2] is not None else None,
                "sector": r[3],
                "industry": r[4],
                "why_listed": "small_cap",
            }
            for r in cur.fetchall()
        ]
    n = storage.replace_watchlist(rows)
    log.info("watchlist size: %d", n)
    return n
