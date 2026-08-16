"""Weekly: build the universe of small/mid-cap common stocks on Euronext Paris.

Targets Euronext Paris main market + Euronext Growth (AL-prefix), excludes
Euronext Access (ML-prefix). Other EU exchanges (XETRA, LSE, HE, ST, CO, OL)
are disabled until verified.

For each exchange we pull EODHD's bulk last-day "extended" feed (one HTTP call per
exchange) which carries, per symbol, the name/type and market cap in the exchange's
local currency. We convert market cap to USD via the FOREX endpoint, keep only common
stocks in the small/mid-cap band ($10M–$10B), filter out Euronext Access (ML) tickers,
and upsert into `assets` keyed by the full EODHD ticker (e.g. "LVMH.PA").

Also cleans up any stale US symbols left over from a prior universe build.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from grapefruit import eodhd_client, storage


log = logging.getLogger(__name__)

# Market cap band applied in the exchange's NATIVE currency before USD
# conversion, so the universe is stable regardless of EUR/USD fluctuations.
# $10M floor catches Euronext Growth; ~$10B ceiling excludes mega-caps.
NATIVE_MARKET_CAP_MIN = 10e6   # ~$10M
NATIVE_MARKET_CAP_MAX = 9e9    # ~€9B / ~$10.4B at EUR/USD 1.16

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
        currency = eodhd_client.exchange_currency(exchange)
        fx = eodhd_client.fetch_fx_rate(currency)
        if fx is None:
            log.warning("no FX rate for %s (%s); skipping exchange", exchange, currency)
            continue

        native = eodhd_client.native_symbol_meta(exchange)
        raw = eodhd_client.fetch_bulk_extended(exchange)
        kept = 0
        excluded_ml = 0
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

            raw_cap = r.get("MarketCapitalization") or r.get("market_capitalization")
            if not isinstance(raw_cap, (int, float)) or raw_cap <= 0:
                continue
            if not (NATIVE_MARKET_CAP_MIN <= raw_cap <= NATIVE_MARKET_CAP_MAX):
                continue
            cap_usd = float(raw_cap) * fx

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
        log.info("%s: %d native commons, %d bulk rows -> %d kept, %d ML excluded (fx %s=%.4f)",
                 exchange, len(native), len(raw), kept, excluded_ml, currency, fx)

    # Exclude symbols with active risk flags.
    risk_flagged = storage.symbols_with_active_risk_flags()
    if risk_flagged:
        log.info("excluding %d risk-flagged symbols from universe", len(risk_flagged))
        rows = [r for r in rows if r["symbol"] not in risk_flagged]

    # Clean up stale US symbols from a prior universe build.
    _cleanup_us_symbols()

    n = storage.upsert_assets(rows)
    symbols = sorted(r["symbol"] for r in rows)
    storage.set_app_state(
        "universe",
        {
            "symbols": symbols,
            "count": len(symbols),
            "exchanges": eodhd_client.EXCHANGES,
            "native_market_cap_min": NATIVE_MARKET_CAP_MIN,
            "native_market_cap_max": NATIVE_MARKET_CAP_MAX,
            "refreshed_at": now.isoformat(),
        },
    )
    log.info("universe: %d stocks across %d exchanges", len(symbols), len(eodhd_client.EXCHANGES))
    return n
