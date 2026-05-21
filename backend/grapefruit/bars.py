import time
from collections.abc import Callable
from datetime import date, datetime, timedelta, timezone

import pandas as pd
from alpaca.data.enums import Adjustment, DataFeed
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame

from grapefruit.alpaca_client import get_data_client

BATCH_SIZE = 200
RATE_LIMIT_PER_MIN = 180  # leave headroom under the 200/min free-tier cap


class TokenBucket:
    """Simple per-minute rate limiter."""

    def __init__(self, per_min: int = RATE_LIMIT_PER_MIN):
        self.per_min = per_min
        self.timestamps: list[float] = []

    def acquire(self) -> None:
        now = time.monotonic()
        self.timestamps = [t for t in self.timestamps if now - t < 60.0]
        if len(self.timestamps) >= self.per_min:
            sleep_for = 60.0 - (now - self.timestamps[0]) + 0.05
            if sleep_for > 0:
                time.sleep(sleep_for)
            now = time.monotonic()
            self.timestamps = [t for t in self.timestamps if now - t < 60.0]
        self.timestamps.append(now)


def _bars_response_to_df(bars_by_symbol: dict) -> pd.DataFrame:
    rows = []
    for symbol, bars in bars_by_symbol.items():
        for b in bars:
            ts = b.timestamp
            if isinstance(ts, datetime):
                ts = ts.date()
            rows.append(
                {
                    "symbol": symbol,
                    "ts": ts,
                    "open": float(b.open),
                    "high": float(b.high),
                    "low": float(b.low),
                    "close": float(b.close),
                    "volume": int(b.volume or 0),
                }
            )
    if not rows:
        return pd.DataFrame(
            columns=["symbol", "ts", "open", "high", "low", "close", "volume"]
        )
    return pd.DataFrame(rows)


def fetch_bars_batch(
    symbols: list[str],
    start: date,
    end: date,
    bucket: TokenBucket,
    max_retries: int = 4,
) -> pd.DataFrame:
    client = get_data_client()
    req = StockBarsRequest(
        symbol_or_symbols=symbols,
        timeframe=TimeFrame.Day,
        start=datetime.combine(start, datetime.min.time(), tzinfo=timezone.utc),
        end=datetime.combine(end, datetime.min.time(), tzinfo=timezone.utc),
        feed=DataFeed.IEX,
        adjustment=Adjustment.ALL,
    )
    attempt = 0
    while True:
        bucket.acquire()
        try:
            resp = client.get_stock_bars(req)
            return _bars_response_to_df(resp.data)
        except Exception as exc:  # noqa: BLE001 — retry on transient errors
            attempt += 1
            if attempt > max_retries:
                raise
            time.sleep(2**attempt)
            if "429" not in str(exc) and "rate" not in str(exc).lower():
                # non-rate-limit error: still retry but log nothing more here
                pass


def fetch_bars(
    symbols: list[str],
    years: int = 5,
    progress: Callable[[int, int, str], None] | None = None,
) -> pd.DataFrame:
    end = date.today()
    start = end - timedelta(days=years * 365 + 30)
    bucket = TokenBucket()
    frames: list[pd.DataFrame] = []
    total = len(symbols)
    for i in range(0, total, BATCH_SIZE):
        batch = symbols[i : i + BATCH_SIZE]
        df = fetch_bars_batch(batch, start, end, bucket)
        if not df.empty:
            frames.append(df)
        if progress:
            progress(min(i + BATCH_SIZE, total), total, f"fetched batch {i // BATCH_SIZE + 1}")
    if not frames:
        return pd.DataFrame(
            columns=["symbol", "ts", "open", "high", "low", "close", "volume"]
        )
    return pd.concat(frames, ignore_index=True)
