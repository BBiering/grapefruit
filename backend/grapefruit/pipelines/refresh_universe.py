"""Weekly: build the universe of small-cap common stocks across the US and
selected European exchanges.

For each exchange we pull EODHD's bulk last-day "extended" feed (one HTTP call
per exchange) which carries, per symbol, the name/type and market cap in the
exchange's local currency. We convert market cap to USD via the FOREX endpoint,
keep only common stocks in the small-cap band, and upsert into `assets` keyed
by the full EODHD ticker (e.g. "BMW.XETRA"). The symbol list is snapshotted to
`app_state['universe']`.

This is also the metadata source (name / market_cap_usd / exchange); the
per-symbol /fundamentals endpoint is not on the current EODHD tier. A separate
sector/industry feed is not available here, so those stay null.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from grapefruit import eodhd_client, storage


log = logging.getLogger(__name__)

# Small-cap band in USD. "Small cap" classically spans ~$300M–$2B.
# A "winner" can re-rate well past the classic small-cap ceiling during its
# surge (e.g. Abivax went from <$2B to ~$8B on a trial readout), so the upper
# bound is generous: we want to catch the company while it was still small AND
# keep showing it after it grew. $10B keeps the lower-mid-cap range in view.
MIN_MARKET_CAP_USD = 300e6
MAX_MARKET_CAP_USD = 10e9


def _market_cap_usd(raw_cap, fx: float) -> float | None:
    if not isinstance(raw_cap, (int, float)) or raw_cap <= 0:
        return None
    return float(raw_cap) * fx


def run() -> int:
    now = datetime.now(timezone.utc)
    rows: list[dict] = []
    seen_isins: set[str] = set()  # dedup the same company across exchanges

    for exchange in eodhd_client.EXCHANGES:
        currency = eodhd_client.exchange_currency(exchange)
        fx = eodhd_client.fetch_fx_rate(currency)
        if fx is None:
            log.warning("no FX rate for %s (%s); skipping exchange", exchange, currency)
            continue

        # Native common stocks only (filters foreign cross-listings like
        # 0RA9.LSE). carries name/isin/currency, which the bulk feed lacks.
        native = eodhd_client.native_symbol_meta(exchange)
        raw = eodhd_client.fetch_bulk_extended(exchange)
        kept = 0
        for r in raw:
            code = r.get("code") or r.get("Code")
            if not code or code not in native:
                continue
            # Skip class-suffixed / preferred-style tickers (e.g. "BRK-A").
            if "/" in code or "." in code:
                continue

            isin = native[code].get("isin")
            if isin and isin in seen_isins:
                continue  # already kept this company on a prior exchange

            cap_usd = _market_cap_usd(
                r.get("MarketCapitalization") or r.get("market_capitalization"), fx
            )
            if cap_usd is None or not (MIN_MARKET_CAP_USD <= cap_usd <= MAX_MARKET_CAP_USD):
                continue

            if isin:
                seen_isins.add(isin)
            rows.append(
                {
                    "symbol": f"{code}.{exchange}",
                    # Prefer the symbol-list name; bulk name can be terse.
                    "name": native[code].get("name") or r.get("name") or r.get("Name"),
                    "exchange": exchange,
                    "sector": None,
                    "industry": None,
                    "market_cap_usd": cap_usd,
                    "refreshed_at": now,
                }
            )
            kept += 1
        log.info("%s: %d native commons, %d bulk rows -> %d small-cap (fx %s=%.4f)",
                 exchange, len(native), len(raw), kept, currency, fx)

    n = storage.upsert_assets(rows)
    symbols = sorted(r["symbol"] for r in rows)
    storage.set_app_state(
        "universe",
        {
            "symbols": symbols,
            "count": len(symbols),
            "exchanges": eodhd_client.EXCHANGES,
            "min_market_cap_usd": MIN_MARKET_CAP_USD,
            "max_market_cap_usd": MAX_MARKET_CAP_USD,
            "refreshed_at": now.isoformat(),
        },
    )
    log.info("universe: %d small-cap common stocks across %d exchanges",
             len(symbols), len(eodhd_client.EXCHANGES))
    return n
