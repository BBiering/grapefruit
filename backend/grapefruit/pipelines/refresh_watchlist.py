"""Weekly: the quantitative screener that produces the look-ahead watchlist.

Pipeline:
  1. Bulk EOD per exchange -> latest close + volume per symbol (1 call/exchange).
  2. Hard filter (USD-converted): price in [$1, $50] AND dollar-volume > $1M.
  3. Rank survivors by 180-day momentum (currency-independent ratio); keep the
     top MOMENTUM_POOL.
  4. For that pool, pull per-symbol fundamentals + insider (Form 4) and compute
     quality/insider scores. Both endpoints are gated on the current EODHD tier
     and degrade to a neutral 50 — momentum then drives the ranking.
  5. combined_score = weighted blend; keep top TOP_N -> watchlist.

Currency: prices are local. usd_factor(exchange) converts price + dollar-volume
to USD; LSE quotes in pence (GBX), so its factor includes a /100.
"""
from __future__ import annotations

import logging

import numpy as np

from grapefruit import eodhd_client, screening, storage


log = logging.getLogger(__name__)

MOMENTUM_POOL = 150  # how many top-momentum names get the expensive fundamentals pass
TOP_N = 40           # final watchlist size


def _usd_factor(exchange: str, fx: float) -> float:
    """Multiplier from a local quoted price to USD. LSE quotes in pence."""
    return fx / 100.0 if exchange == "LSE" else fx


def run() -> int:
    assets = storage.load_assets_map()
    if not assets:
        log.warning("no symbols in `assets`; run refresh_universe first")
        return 0
    momentum = storage.momentum_180d_all()

    # ---- steps 1-2: bulk feed + hard filter (USD-converted) -----------------
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
            if not screening.passes_hard_filter(usd_price, usd_dv):
                continue
            mom = momentum.get(symbol)
            if mom is None:
                continue  # need 180d history to rank
            candidates.append(
                {
                    "symbol": symbol,
                    "exchange": exchange,
                    "usd_price": usd_price,
                    "dollar_volume": usd_dv,
                    "momentum_180d": mom,
                    "meta": meta,
                }
            )

    if not candidates:
        log.warning("no candidates passed the hard filter")
        storage.replace_watchlist([])
        return 0
    log.info("%d candidates passed the hard filter", len(candidates))

    # ---- step 3: keep the top MOMENTUM_POOL by momentum ---------------------
    candidates.sort(key=lambda c: c["momentum_180d"], reverse=True)
    pool = candidates[:MOMENTUM_POOL]

    # ---- step 4: fundamentals + insider for the pool ------------------------
    for c in pool:
        ni, pm = eodhd_client.fundamentals_highlights(
            eodhd_client.fetch_fundamentals(c["symbol"])
        )
        c["net_income"] = ni
        c["profit_margin"] = pm
        c["quality_score"] = screening.quality_score(ni, pm)
        c["insider_score"] = screening.insider_score(
            eodhd_client.fetch_insider_transactions(c["symbol"])
        )

    # ---- step 5: combined score (momentum percentile within the pool) -------
    moms = np.array([c["momentum_180d"] for c in pool])
    for c in pool:
        pct_rank = float((moms < c["momentum_180d"]).mean() * 100.0)
        c["momentum_score"] = pct_rank
        c["combined_score"] = screening.combined_score(
            pct_rank, c["quality_score"], c["insider_score"]
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
            "why_listed": "screened_liquid_momentum",
            "dollar_volume": c["dollar_volume"],
            "momentum_180d": c["momentum_180d"],
            "momentum_score": c["momentum_score"],
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
