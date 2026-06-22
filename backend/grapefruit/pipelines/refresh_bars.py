"""Daily / on-demand: pull only the bars missing since the last run.

For each symbol in `assets`, fetch [latest_bar_date+1, today] from EODHD.
If no bars exist yet, pulls the last 5 years (initial run).
"""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta

import pandas as pd

from grapefruit import eodhd_client, storage


log = logging.getLogger(__name__)

_INITIAL_LOOKBACK_DAYS = 5 * 365 + 30
_MAX_WORKERS = 16


def _fetch_symbol(symbol: str, today: date) -> pd.DataFrame:
    latest = storage.latest_bar_date(symbol)
    start = (latest + timedelta(days=1)) if latest else today - timedelta(days=_INITIAL_LOOKBACK_DAYS)
    if start > today:
        return pd.DataFrame()
    try:
        rows = eodhd_client.fetch_eod(symbol, start, today)
    except Exception as exc:  # noqa: BLE001
        log.warning("fetch_eod failed for %s: %s", symbol, exc)
        return pd.DataFrame()
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    # EODHD returns: date, open, high, low, close, adjusted_close, volume
    if "adjusted_close" in df.columns:
        df["close"] = df["adjusted_close"]
    df["symbol"] = symbol
    df["ts"] = pd.to_datetime(df["date"]).dt.date
    return df[["symbol", "ts", "open", "high", "low", "close", "volume"]]


def run() -> int:
    today = date.today()
    symbols = storage.symbols_in_assets()
    if not symbols:
        log.warning("no symbols in `assets`; run refresh_universe first")
        return 0

    total = 0
    with ThreadPoolExecutor(max_workers=_MAX_WORKERS) as ex:
        futs = {ex.submit(_fetch_symbol, s, today): s for s in symbols}
        batch: list[pd.DataFrame] = []
        for i, fut in enumerate(as_completed(futs), start=1):
            df = fut.result()
            if not df.empty:
                batch.append(df)
            if i % 200 == 0:
                if batch:
                    total += storage.upsert_bars(pd.concat(batch, ignore_index=True))
                    batch = []
                log.info("processed %d/%d symbols (rows upserted so far: %d)", i, len(symbols), total)
        if batch:
            total += storage.upsert_bars(pd.concat(batch, ignore_index=True))
    log.info("refresh_bars done: %d symbols, %d rows upserted", len(symbols), total)
    return total
