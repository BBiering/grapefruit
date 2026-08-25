"""Weekly: build the universe of Biotech common stocks on Euronext Paris.

Targets Euronext Paris main market + Euronext Growth (AL-prefix), excludes
Euronext Access (ML-prefix). Other EU exchanges (XETRA, LSE, HE, ST, CO, OL)
are disabled until verified.

For each exchange we pull EODHD's bulk last-day "extended" feed (one HTTP call per
exchange) which carries, per symbol, the name/type and market cap in the exchange's
local currency. We convert market cap to USD via the FOREX endpoint, keep only common
stocks priced under $100/€100 in their native currency, filter out Euronext Access
(ML) tickers, and upsert into `assets` keyed by the full EODHD ticker (e.g. "LVMH.PA").

The final Biotech-only filter is applied by refresh_sectors — after industry data is
populated, non-Biotechnology stocks are dropped from the universe.

Also cleans up any stale US symbols left over from a prior universe build.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from grapefruit import eodhd_client, storage


log = logging.getLogger(__name__)

# Price ceiling per exchange, expressed in the exchange's NATIVE currency
# (a ~$200-equivalent for ten-bagger hunting).
MAX_NATIVE_PRICE: dict[str, float] = {
    "US": 200.0,   # United States (USD)
    "ST": 1900.0,  # Sweden  (SEK)
    "LSE": 160.0,  # UK      (GBP)
    "PA": 170.0,   # France  (EUR)
    "SW": 160.0,   # Switzerland (CHF)
    "CO": 1280.0,  # Denmark (DKK)
    "XETRA": 170.0,# Germany (EUR)
}

# Minimum market cap (USD): exclude nano-caps (<$50M) and micro-caps
# ($50M-$300M) to avoid illiquid shells. Applied to the USD-converted cap.
MIN_MARKET_CAP_USD = 300e6

# Ticker prefixes for Euronext segments on the PA exchange.
# AL* = Euronext Growth (formerly Alternext) — include.
# ML* = Euronext Access / Access+ (formerly Marché Libre) — exclude for now.
_EXCLUDE_PREFIXES = ("ML",)


def _cleanup_us_symbols() -> int:
    """Delete stale US-tagged symbols from assets + bars."""
    counts = storage.cleanup_symbols_by_exchange("US")
    if counts["assets"] or counts["bars"]:
        log.info("cleaned up US symbols: %d assets, %d bar rows", counts["assets"], counts["bars"])
    return counts["assets"]


def run() -> int:
    now = datetime.now(timezone.utc)
    rows: list[dict] = []
    seen_isins: set[str] = set()

    for exchange in eodhd_client.EXCHANGES:
        price_ceiling = MAX_NATIVE_PRICE.get(exchange, 85.0)
        currency = eodhd_client.exchange_currency(exchange)
        fx = eodhd_client.fetch_fx_rate(currency)
        if fx is None:
            log.warning("no FX rate for %s (%s); skipping exchange", exchange, currency)
            continue

        native = eodhd_client.native_symbol_meta(exchange)
        raw = eodhd_client.fetch_bulk_extended(exchange)
        kept = 0
        excluded_ml = 0
        excluded_price = 0
        excluded_cap = 0
        for r in raw:
            code = r.get("code") or r.get("Code")
            if not code or code not in native:
                continue
            # Skip class-suffixed / preferred-style tickers.
            if "/" in code or "." in code:
                continue

            # Exclude Euronext Access (ML-prefix) tickers.
            if any(code.startswith(p) for p in _EXCLUDE_PREFIXES):
                excluded_ml += 1
                continue

            isin = native[code].get("isin")
            if isin and isin in seen_isins:
                continue

            # Price filter: positive close under the exchange's $100-equivalent ceiling.
            close = r.get("close") or r.get("adjusted_close")
            if not isinstance(close, (int, float)) or close <= 0 or close > price_ceiling:
                excluded_price += 1
                continue

            # Market cap in USD: required and must be >= small-cap floor.
            raw_cap = r.get("MarketCapitalization") or r.get("market_capitalization")
            if not isinstance(raw_cap, (int, float)) or raw_cap <= 0:
                continue
            cap_usd = float(raw_cap) * fx
            if cap_usd < MIN_MARKET_CAP_USD:
                excluded_cap += 1
                continue

            if isin:
                seen_isins.add(isin)
            rows.append(
                {
                    "symbol": f"{code}.{exchange}",
                    "name": native[code].get("name") or r.get("name") or r.get("Name"),
                    "exchange": exchange,
                    "sector": None,
                    "industry": None,
                    "market_cap_usd": cap_usd,
                    "refreshed_at": now,
                }
            )
            kept += 1
        log.info("%s: %d native commons, %d bulk rows -> %d kept, %d ML excluded, %d price excluded, %d cap excluded (fx %s=%.4f)",
                 exchange, len(native), len(raw), kept, excluded_ml, excluded_price, excluded_cap, currency, fx)

    # Only purge stale US symbols when US is not one of the active exchanges.
    if "US" not in eodhd_client.EXCHANGES:
        _cleanup_us_symbols()

    n = storage.upsert_assets(rows)
    symbols = sorted(r["symbol"] for r in rows)
    storage.set_app_state(
        "universe",
        {
            "symbols": symbols,
            "count": len(symbols),
            "exchanges": eodhd_client.EXCHANGES,
            "max_native_price": MAX_NATIVE_PRICE,
            "refreshed_at": now.isoformat(),
        },
    )
    log.info("universe: %d stocks across %d exchanges", len(symbols), len(eodhd_client.EXCHANGES))
    return n
