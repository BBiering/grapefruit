from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta

import pandas as pd

from grapefruit import eodhd_client

MAX_WORKERS = 16  # EODHD_BUCKET (900/min) is the real throttle; workers just block on it

_COLUMNS = ["symbol", "ts", "open", "high", "low", "close", "volume"]


def _eod_to_rows(symbol: str, bars: list[dict]) -> list[dict]:
    """Map EODHD EOD bars to our row shape, scaling OHLC to be split/dividend-adjusted.

    EODHD's open/high/low/close are unadjusted; adjusted_close is fully adjusted.
    We store the adjusted close and scale OHLC by the same ratio so candles stay
    internally consistent (matches Alpaca's Adjustment.ALL behavior).
    """
    rows = []
    for b in bars:
        close = b.get("close")
        adj = b.get("adjusted_close")
        ts = b.get("date")
        if close in (None, 0) or adj is None or ts is None:
            continue
        ratio = float(adj) / float(close)
        rows.append(
            {
                "symbol": symbol,
                "ts": date.fromisoformat(ts),
                "open": float(b["open"]) * ratio,
                "high": float(b["high"]) * ratio,
                "low": float(b["low"]) * ratio,
                "close": float(adj),
                "volume": int(b.get("volume") or 0),
            }
        )
    return rows


def fetch_bars_one(symbol: str, start: date, end: date) -> list[dict]:
    """Fetch + adjust daily bars for a single symbol. Never raises on data issues."""
    bars = eodhd_client.fetch_eod(symbol, start, end)
    return _eod_to_rows(symbol, bars)


def fetch_bars(
    symbols: list[str],
    years: int = 5,
    progress: Callable[[int, int, str], None] | None = None,
) -> pd.DataFrame:
    end = date.today()
    start = end - timedelta(days=years * 365 + 30)
    total = len(symbols)
    rows: list[dict] = []
    done = 0

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = {pool.submit(fetch_bars_one, sym, start, end): sym for sym in symbols}
        for fut in as_completed(futures):
            sym = futures[fut]
            try:
                rows.extend(fut.result())
            except Exception:  # noqa: BLE001 — skip a symbol that failed all retries
                pass
            done += 1
            if progress:
                progress(done, total, f"fetched {sym} ({done}/{total})")

    if not rows:
        return pd.DataFrame(columns=_COLUMNS)
    return pd.DataFrame(rows)
