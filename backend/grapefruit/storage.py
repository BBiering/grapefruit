import threading
from contextlib import contextmanager
from datetime import date, datetime, timezone

import duckdb
import pandas as pd

from grapefruit.config import DUCKDB_PATH


_lock = threading.Lock()
_conn: duckdb.DuckDBPyConnection | None = None


def _get_conn() -> duckdb.DuckDBPyConnection:
    global _conn
    if _conn is None:
        _conn = duckdb.connect(str(DUCKDB_PATH))
    return _conn


@contextmanager
def _use_db():
    """Yield a cursor from the shared connection under a lock."""
    with _lock:
        con = _get_conn()
        yield con


def init_db() -> None:
    with _use_db() as con:
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS bars (
                symbol VARCHAR NOT NULL,
                ts DATE NOT NULL,
                open DOUBLE,
                high DOUBLE,
                low DOUBLE,
                close DOUBLE,
                volume BIGINT,
                PRIMARY KEY (symbol, ts)
            )
            """
        )
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS hits (
                symbol VARCHAR NOT NULL,
                window_days INTEGER NOT NULL,
                threshold DOUBLE NOT NULL,
                start_ts DATE NOT NULL,
                end_ts DATE NOT NULL,
                trough_price DOUBLE,
                peak_price DOUBLE,
                multiplier DOUBLE,
                scanned_at TIMESTAMP
            )
            """
        )
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS assets (
                symbol VARCHAR PRIMARY KEY,
                name VARCHAR,
                exchange VARCHAR,
                sector VARCHAR,
                industry VARCHAR,
                refreshed_at TIMESTAMP
            )
            """
        )
        con.execute("CREATE INDEX IF NOT EXISTS bars_symbol_idx ON bars(symbol)")
        con.execute("CREATE INDEX IF NOT EXISTS hits_window_idx ON hits(window_days)")


def upsert_bars(df: pd.DataFrame) -> int:
    if df.empty:
        return 0
    with _use_db() as con:
        con.register("incoming", df)
        con.execute(
            """
            INSERT INTO bars SELECT symbol, ts, open, high, low, close, volume FROM incoming
            ON CONFLICT (symbol, ts) DO UPDATE SET
                open = EXCLUDED.open,
                high = EXCLUDED.high,
                low = EXCLUDED.low,
                close = EXCLUDED.close,
                volume = EXCLUDED.volume
            """
        )
        con.unregister("incoming")
        return len(df)


def load_symbol(symbol: str, start: date | None = None, end: date | None = None) -> pd.DataFrame:
    q = "SELECT ts, open, high, low, close, volume FROM bars WHERE symbol = ?"
    params: list = [symbol]
    if start:
        q += " AND ts >= ?"
        params.append(start)
    if end:
        q += " AND ts <= ?"
        params.append(end)
    q += " ORDER BY ts"
    with _use_db() as con:
        return con.execute(q, params).df()


def last_ts(symbol: str) -> date | None:
    with _use_db() as con:
        row = con.execute(
            "SELECT MAX(ts) FROM bars WHERE symbol = ?", [symbol]
        ).fetchone()
        return row[0] if row and row[0] else None


def symbols_with_bars() -> list[str]:
    with _use_db() as con:
        rows = con.execute("SELECT DISTINCT symbol FROM bars ORDER BY symbol").fetchall()
        return [r[0] for r in rows]


def hit_symbols_missing_metadata() -> list[str]:
    """Symbols that have at least one hit but no usable name in `assets`."""
    with _use_db() as con:
        rows = con.execute(
            """
            SELECT DISTINCT h.symbol
            FROM hits h
            LEFT JOIN assets a ON a.symbol = h.symbol
            WHERE a.name IS NULL OR a.name = ''
            ORDER BY h.symbol
            """
        ).fetchall()
        return [r[0] for r in rows]


def save_hits(rows: list[dict], window_days: int, threshold: float) -> None:
    if not rows:
        return
    scanned_at = datetime.now(timezone.utc)
    df = pd.DataFrame(rows)
    df["window_days"] = window_days
    df["threshold"] = threshold
    df["scanned_at"] = scanned_at
    with _use_db() as con:
        con.execute(
            "DELETE FROM hits WHERE window_days = ? AND threshold = ?",
            [window_days, threshold],
        )
        con.register("incoming_hits", df)
        con.execute(
            """
            INSERT INTO hits
                (symbol, window_days, threshold, start_ts, end_ts, trough_price, peak_price, multiplier, scanned_at)
            SELECT symbol, window_days, threshold, start_ts, end_ts, trough_price, peak_price, multiplier, scanned_at
            FROM incoming_hits
            """
        )
        con.unregister("incoming_hits")


def query_hits(
    window_weeks: int | None = None,
    min_multiplier: float | None = None,
    max_days_since_peak: int | None = None,
    min_peak_retention: float | None = None,
) -> list[dict]:
    q = "SELECT symbol, window_days, threshold, start_ts, end_ts, trough_price, peak_price, multiplier, scanned_at FROM hits WHERE 1=1"
    params: list = []
    if window_weeks is not None:
        q += " AND window_days = ?"
        params.append(window_weeks * 5)
    if min_multiplier is not None:
        q += " AND multiplier >= ?"
        params.append(min_multiplier)
    q += " ORDER BY multiplier DESC"
    with _use_db() as con:
        cur = con.execute(q, params)
        rows = cur.fetchall()
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, r, strict=True)) for r in rows]
