from datetime import date, datetime, timezone

import duckdb
import pandas as pd

from grapefruit.config import DUCKDB_PATH


def _connect() -> duckdb.DuckDBPyConnection:
    con = duckdb.connect(str(DUCKDB_PATH))
    return con


def init_db() -> None:
    con = _connect()
    try:
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
        con.execute("CREATE INDEX IF NOT EXISTS bars_symbol_idx ON bars(symbol)")
        con.execute("CREATE INDEX IF NOT EXISTS hits_window_idx ON hits(window_days)")
    finally:
        con.close()


def upsert_bars(df: pd.DataFrame) -> int:
    if df.empty:
        return 0
    con = _connect()
    try:
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
        return len(df)
    finally:
        con.close()


def load_symbol(symbol: str, start: date | None = None, end: date | None = None) -> pd.DataFrame:
    con = _connect()
    try:
        q = "SELECT ts, open, high, low, close, volume FROM bars WHERE symbol = ?"
        params: list = [symbol]
        if start:
            q += " AND ts >= ?"
            params.append(start)
        if end:
            q += " AND ts <= ?"
            params.append(end)
        q += " ORDER BY ts"
        return con.execute(q, params).df()
    finally:
        con.close()


def last_ts(symbol: str) -> date | None:
    con = _connect()
    try:
        row = con.execute(
            "SELECT MAX(ts) FROM bars WHERE symbol = ?", [symbol]
        ).fetchone()
        return row[0] if row and row[0] else None
    finally:
        con.close()


def symbols_with_bars() -> list[str]:
    con = _connect()
    try:
        rows = con.execute("SELECT DISTINCT symbol FROM bars ORDER BY symbol").fetchall()
        return [r[0] for r in rows]
    finally:
        con.close()


def save_hits(rows: list[dict], window_days: int, threshold: float) -> None:
    if not rows:
        return
    con = _connect()
    try:
        scanned_at = datetime.now(timezone.utc)
        con.execute(
            "DELETE FROM hits WHERE window_days = ? AND threshold = ?",
            [window_days, threshold],
        )
        df = pd.DataFrame(rows)
        df["window_days"] = window_days
        df["threshold"] = threshold
        df["scanned_at"] = scanned_at
        con.register("incoming_hits", df)
        con.execute(
            """
            INSERT INTO hits
                (symbol, window_days, threshold, start_ts, end_ts, trough_price, peak_price, multiplier, scanned_at)
            SELECT symbol, window_days, threshold, start_ts, end_ts, trough_price, peak_price, multiplier, scanned_at
            FROM incoming_hits
            """
        )
    finally:
        con.close()


def query_hits(
    window_weeks: int | None = None,
    min_multiplier: float | None = None,
) -> list[dict]:
    con = _connect()
    try:
        q = "SELECT symbol, window_days, threshold, start_ts, end_ts, trough_price, peak_price, multiplier, scanned_at FROM hits WHERE 1=1"
        params: list = []
        if window_weeks is not None:
            q += " AND window_days = ?"
            params.append(window_weeks * 5)  # 5 trading days/week
        if min_multiplier is not None:
            q += " AND multiplier >= ?"
            params.append(min_multiplier)
        q += " ORDER BY multiplier DESC"
        rows = con.execute(q, params).fetchall()
        cols = [d[0] for d in con.description]
        return [dict(zip(cols, r, strict=True)) for r in rows]
    finally:
        con.close()
