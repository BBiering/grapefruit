"""Weekly: the quantitative screener that produces the look-ahead watchlist.

New Strategy-Focused Pipeline:
  1. Bulk EOD per exchange -> latest close + volume per symbol (1 call/exchange).
  2. For ALL universe symbols, pull fundamentals and compute:
     - momentum_180d (for ranking, not filtering)
     - quality_score (for filtering: must be profitable, score > 50)
     - insider_score (for context)
  3. FILTER by quality: keep only quality_score > 50 (profitable companies).
  4. Rank by combined_score (momentum 50%, quality 30%, insider 20%).
  5. Keep top TOP_N -> watchlist.

No price or volume filters - we want all companies ≤$10B market cap.
Quality (profitability) is the primary filter; momentum is for ranking.
"""
from __future__ import annotations

import logging

import numpy as np

from grapefruit import eodhd_client, screening, storage


log = logging.getLogger(__name__)

TOP_N = 40  # final watchlist size
MIN_QUALITY_SCORE = 50  # minimum quality score (50 = neutral, >50 = profitable)
LIQUIDITY_POOL = 300  # pre-filter by liquidity to keep API calls reasonable


def _usd_factor(exchange: str, fx: float) -> float:
    """Multiplier from a local quoted price to USD. LSE quotes in pence."""
    return fx / 100.0 if exchange == "LSE" else fx


def run() -> int:
    assets = storage.load_assets_map()
    if not assets:
        log.warning("no symbols in `assets`; run refresh_universe first")
        return 0

    # ---- step 1-2: build candidates from all universe symbols ----------------
    candidates: list[dict] = []
    for exchange in eodhd_client.EXCHANGES:
        currency = eodhd_client.exchange_currency(exchange)
        fx = eodhd_client.fetch_fx_rate(currency)
        if fx is None:
            log.warning("no FX rate for %s (%s); skipping", exchange, currency)
            continue
        factor = _usd_factor(exchange, fx)
        for r in eodhd_client.fetch_bulk_extended(exchange):
            code = r.get("code") or r.get("Code")
            if not code:
                continue
            symbol = f"{code}.{exchange}"
            meta = assets.get(symbol)
            if meta is None:
                continue  # not in the curated universe
            close = r.get("close") or r.get("adjusted_close")
            volume = r.get("volume")
            if not isinstance(close, (int, float)) or not isinstance(volume, (int, float)):
                continue
            usd_price = float(close) * factor
            usd_dv = float(close) * float(volume) * factor
            candidates.append(
                {
                    "symbol": symbol,
                    "exchange": exchange,
                    "usd_price": usd_price,
                    "dollar_volume": usd_dv,
                    "meta": meta,
                }
            )

    if not candidates:
        log.warning("no candidates in universe")
        storage.replace_watchlist([])
        return 0
    log.info("%d total candidates from universe", len(candidates))

    # ---- step 3: pre-filter by liquidity to keep API calls reasonable -------
    # Sort by dollar volume and keep top LIQUIDITY_POOL
    candidates.sort(key=lambda c: c["dollar_volume"], reverse=True)
    liquid_pool = candidates[:LIQUIDITY_POOL]
    log.info("kept top %d by liquidity (${%.0f}M+ daily volume)",
             len(liquid_pool), liquid_pool[-1]["dollar_volume"] / 1e6 if liquid_pool else 0)

    # ---- step 4: fetch fundamentals for liquid pool --------------------------
    for i, c in enumerate(liquid_pool, start=1):
        if i % 50 == 0:
            log.info("fetching fundamentals: %d/%d", i, len(liquid_pool))
        fundamentals = eodhd_client.fetch_fundamentals(c["symbol"])
        ni, pm = eodhd_client.fundamentals_highlights(fundamentals)
        c["net_income"] = ni
        c["profit_margin"] = pm
        c["quality_score"] = screening.quality_score(ni, pm)
        c["insider_score"] = screening.insider_score(
            eodhd_client.fetch_insider_transactions(c["symbol"])
        )

    # ---- step 5: filter by quality (must be profitable) ---------------------
    quality_filtered = [c for c in liquid_pool if c["quality_score"] > MIN_QUALITY_SCORE]
    if not quality_filtered:
        log.warning("no candidates passed quality filter (score > %d)", MIN_QUALITY_SCORE)
        storage.replace_watchlist([])
        return 0
    log.info("%d/%d passed quality filter", len(quality_filtered), len(liquid_pool))

    # ---- step 6: compute combined score and rank ----------------------------
    pool = quality_filtered
    for c in pool:
        # Combined score: 60% quality, 40% insider activity
        c["combined_score"] = screening.combined_score(
            c["quality_score"], c["insider_score"]
        )

    pool.sort(key=lambda c: c["combined_score"], reverse=True)
    top = pool[:TOP_N]

    rows = [
        {
            "symbol": c["symbol"],
            "last_close": round(c["usd_price"], 4),
            "market_cap_usd": c["meta"].get("market_cap_usd"),
            "sector": c["meta"].get("sector"),
            "industry": c["meta"].get("industry"),
            "why_listed": "screened_quality_insider",
            "dollar_volume": c["dollar_volume"],
            "quality_score": c["quality_score"],
            "insider_score": c["insider_score"],
            "combined_score": c["combined_score"],
            "net_income": c.get("net_income"),
            "profit_margin": c.get("profit_margin"),
            "rank": i + 1,
        }
        for i, c in enumerate(top)
    ]
    n = storage.replace_watchlist(rows)
    log.info("watchlist: %d screened from %d candidates", n, len(candidates))
    return n
