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
    q = """
        WITH latest AS (
            SELECT b.symbol, b.close AS current_price, b.ts AS last_ts
            FROM bars b
            JOIN (
                SELECT symbol, MAX(ts) AS mx FROM bars GROUP BY symbol
            ) m ON m.symbol = b.symbol AND m.mx = b.ts
        )
        SELECT
            h.symbol, h.window_days, h.threshold,
            h.start_ts, h.end_ts,
            h.trough_price, h.peak_price, h.multiplier, h.scanned_at,
            a.name, a.exchange, a.sector, a.industry,
            l.current_price, l.last_ts,
            CASE WHEN l.last_ts IS NULL THEN NULL
                 ELSE CAST(date_diff('day', h.end_ts, l.last_ts) AS INTEGER)
            END AS days_since_peak,
            CASE WHEN h.peak_price > 0 AND l.current_price IS NOT NULL
                 THEN l.current_price / h.peak_price
                 ELSE NULL
            END AS peak_retention
        FROM hits h
        LEFT JOIN assets a ON a.symbol = h.symbol
        LEFT JOIN latest l ON l.symbol = h.symbol
        WHERE 1=1
    """
    params: list = []
    if window_weeks is not None:
        q += " AND h.window_days = ?"
        params.append(window_weeks * 5)
    if min_multiplier is not None:
        q += " AND h.multiplier >= ?"
        params.append(min_multiplier)
    if max_days_since_peak is not None:
        q += " AND date_diff('day', h.end_ts, l.last_ts) <= ?"
        params.append(max_days_since_peak)
    if min_peak_retention is not None:
        q += " AND (h.peak_price > 0 AND l.current_price / h.peak_price >= ?)"
        params.append(min_peak_retention)
    q += " ORDER BY h.multiplier DESC"
    with _use_db() as con:
        cur = con.execute(q, params)
        rows = cur.fetchall()
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, r, strict=True)) for r in rows]


def upsert_asset(row: dict) -> None:
    df = pd.DataFrame([row])
    with _use_db() as con:
        con.register("incoming_asset", df)
        con.execute(
            """
            INSERT INTO assets (symbol, name, exchange, sector, industry, refreshed_at)
            SELECT symbol, name, exchange, sector, industry, refreshed_at FROM incoming_asset
            ON CONFLICT (symbol) DO UPDATE SET
                name = EXCLUDED.name,
                exchange = EXCLUDED.exchange,
                sector = EXCLUDED.sector,
                industry = EXCLUDED.industry,
                refreshed_at = EXCLUDED.refreshed_at
            """
        )
        con.unregister("incoming_asset")


def load_asset(symbol: str) -> dict | None:
    with _use_db() as con:
        cur = con.execute(
            "SELECT symbol, name, exchange, sector, industry, refreshed_at FROM assets WHERE symbol = ?",
            [symbol],
        )
        row = cur.fetchone()
        if not row:
            return None
        cols = [d[0] for d in cur.description]
        return dict(zip(cols, row, strict=True))
