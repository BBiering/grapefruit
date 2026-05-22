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
                market_cap_usd DOUBLE,
                refreshed_at TIMESTAMP
            )
            """
        )
        # Older databases may predate market_cap_usd; add it idempotently.
        con.execute("ALTER TABLE assets ADD COLUMN IF NOT EXISTS market_cap_usd DOUBLE")
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS catalysts (
                symbol VARCHAR NOT NULL,
                end_ts DATE NOT NULL,
                headline VARCHAR,
                summary VARCHAR,
                spike_explanation VARCHAR,
                was_foreseeable BOOLEAN,
                foreseeable_evidence VARCHAR,
                fetched_at TIMESTAMP,
                PRIMARY KEY (symbol, end_ts)
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


PRE_TROUGH_LOOKBACK_DAYS = 180


def query_hits(
    window_weeks: int | None = None,
    min_multiplier: float | None = None,
    max_days_since_peak: int | None = None,
    min_peak_retention: float | None = None,
    min_breakout_ratio: float | None = None,
    industry: str | None = None,
    pre_trough_lookback_days: int = PRE_TROUGH_LOOKBACK_DAYS,
) -> list[dict]:
    q = """
        WITH latest AS (
            SELECT b.symbol, b.close AS current_price, b.ts AS last_ts
            FROM bars b
            JOIN (
                SELECT symbol, MAX(ts) AS mx FROM bars GROUP BY symbol
            ) m ON m.symbol = b.symbol AND m.mx = b.ts
        ),
        pre_trough AS (
            SELECT h.symbol, h.start_ts, h.end_ts, MAX(b.close) AS pre_high
            FROM hits h
            LEFT JOIN bars b
              ON b.symbol = h.symbol
             AND b.ts < h.start_ts
             AND b.ts >= h.start_ts - CAST(? AS INTEGER) * INTERVAL 1 DAY
            GROUP BY h.symbol, h.start_ts, h.end_ts
        )
        SELECT
            h.symbol, h.window_days, h.threshold,
            h.start_ts, h.end_ts,
            h.trough_price, h.peak_price, h.multiplier, h.scanned_at,
            a.name, a.exchange, a.sector, a.industry, a.market_cap_usd,
            l.current_price, l.last_ts,
            CASE WHEN l.last_ts IS NULL THEN NULL
                 ELSE CAST(date_diff('day', h.end_ts, l.last_ts) AS INTEGER)
            END AS days_since_peak,
            CASE WHEN h.peak_price > 0 AND l.current_price IS NOT NULL
                 THEN l.current_price / h.peak_price
                 ELSE NULL
            END AS peak_retention,
            p.pre_high,
            CASE WHEN p.pre_high IS NULL OR p.pre_high <= 0 THEN NULL
                 ELSE h.peak_price / p.pre_high
            END AS breakout_ratio,
            c.headline, c.summary AS catalyst_summary, c.was_foreseeable
        FROM hits h
        LEFT JOIN assets a ON a.symbol = h.symbol
        LEFT JOIN latest l ON l.symbol = h.symbol
        LEFT JOIN pre_trough p
          ON p.symbol = h.symbol AND p.start_ts = h.start_ts AND p.end_ts = h.end_ts
        LEFT JOIN catalysts c ON c.symbol = h.symbol AND c.end_ts = h.end_ts
        WHERE 1=1
    """
    params: list = [pre_trough_lookback_days]
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
    if min_breakout_ratio is not None:
        # Keep rows where we know the breakout cleared the threshold. NULL
        # pre_high means we have no pre-trough bars at all (newly listed) -
        # those are not rebounds, so let them through.
        q += " AND (p.pre_high IS NULL OR p.pre_high <= 0 OR h.peak_price / p.pre_high >= ?)"
        params.append(min_breakout_ratio)
    if industry is not None:
        q += " AND a.industry = ?"
        params.append(industry)
    q += " ORDER BY h.multiplier DESC"
    with _use_db() as con:
        cur = con.execute(q, params)
        rows = cur.fetchall()
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, r, strict=True)) for r in rows]


_ASSET_COLS = ("symbol", "name", "exchange", "sector", "industry", "market_cap_usd", "refreshed_at")


def upsert_asset(row: dict) -> None:
    row = {col: row.get(col) for col in _ASSET_COLS}
    df = pd.DataFrame([row])
    with _use_db() as con:
        con.register("incoming_asset", df)
        con.execute(
            """
            INSERT INTO assets (symbol, name, exchange, sector, industry, market_cap_usd, refreshed_at)
            SELECT symbol, name, exchange, sector, industry, market_cap_usd, refreshed_at FROM incoming_asset
            ON CONFLICT (symbol) DO UPDATE SET
                name = EXCLUDED.name,
                exchange = EXCLUDED.exchange,
                sector = EXCLUDED.sector,
                industry = EXCLUDED.industry,
                market_cap_usd = EXCLUDED.market_cap_usd,
                refreshed_at = EXCLUDED.refreshed_at
            """
        )
        con.unregister("incoming_asset")


def load_asset(symbol: str) -> dict | None:
    with _use_db() as con:
        cur = con.execute(
            "SELECT symbol, name, exchange, sector, industry, market_cap_usd, refreshed_at FROM assets WHERE symbol = ?",
            [symbol],
        )
        row = cur.fetchone()
        if not row:
            return None
        cols = [d[0] for d in cur.description]
        return dict(zip(cols, row, strict=True))


def symbols_with_market_cap_below(cap_usd: float) -> list[str]:
    with _use_db() as con:
        rows = con.execute(
            "SELECT symbol FROM assets WHERE market_cap_usd IS NOT NULL AND market_cap_usd > 0 AND market_cap_usd <= ?",
            [cap_usd],
        ).fetchall()
        return [r[0] for r in rows]


def symbols_with_last_close_below(price_usd: float) -> list[str]:
    """Symbols whose most recent cached close is at or below `price_usd`."""
    with _use_db() as con:
        rows = con.execute(
            """
            WITH latest AS (
                SELECT b.symbol, b.close FROM bars b
                JOIN (SELECT symbol, MAX(ts) AS mx FROM bars GROUP BY symbol) m
                  ON m.symbol = b.symbol AND m.mx = b.ts
            )
            SELECT symbol FROM latest WHERE close > 0 AND close <= ?
            """,
            [price_usd],
        ).fetchall()
        return [r[0] for r in rows]


_CATALYST_COLS = (
    "symbol",
    "end_ts",
    "headline",
    "summary",
    "spike_explanation",
    "was_foreseeable",
    "foreseeable_evidence",
    "fetched_at",
)


def upsert_catalyst(row: dict) -> None:
    row = {col: row.get(col) for col in _CATALYST_COLS}
    df = pd.DataFrame([row])
    with _use_db() as con:
        con.register("incoming_catalyst", df)
        con.execute(
            """
            INSERT INTO catalysts
                (symbol, end_ts, headline, summary, spike_explanation,
                 was_foreseeable, foreseeable_evidence, fetched_at)
            SELECT symbol, end_ts, headline, summary, spike_explanation,
                   was_foreseeable, foreseeable_evidence, fetched_at
            FROM incoming_catalyst
            ON CONFLICT (symbol, end_ts) DO UPDATE SET
                headline = EXCLUDED.headline,
                summary = EXCLUDED.summary,
                spike_explanation = EXCLUDED.spike_explanation,
                was_foreseeable = EXCLUDED.was_foreseeable,
                foreseeable_evidence = EXCLUDED.foreseeable_evidence,
                fetched_at = EXCLUDED.fetched_at
            """
        )
        con.unregister("incoming_catalyst")


def hits_without_catalyst(limit: int | None = None) -> list[dict]:
    q = """
        SELECT h.symbol, h.start_ts, h.end_ts, h.trough_price, h.peak_price, h.multiplier
        FROM hits h
        LEFT JOIN catalysts c ON c.symbol = h.symbol AND c.end_ts = h.end_ts
        WHERE c.symbol IS NULL
        ORDER BY h.multiplier DESC
    """
    params: list = []
    if limit:
        q += " LIMIT ?"
        params.append(limit)
    with _use_db() as con:
        cur = con.execute(q, params)
        rows = cur.fetchall()
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, r, strict=True)) for r in rows]


def list_hit_industries() -> list[str]:
    """Distinct, non-null industries among symbols that appear in `hits`."""
    with _use_db() as con:
        rows = con.execute(
            """
            SELECT DISTINCT a.industry
            FROM hits h JOIN assets a ON a.symbol = h.symbol
            WHERE a.industry IS NOT NULL AND a.industry != ''
            ORDER BY a.industry
            """
        ).fetchall()
        return [r[0] for r in rows]


def counts() -> dict:
    with _use_db() as con:
        return {
            "bar_symbols": con.execute("SELECT COUNT(DISTINCT symbol) FROM bars").fetchone()[0],
            "hits": con.execute("SELECT COUNT(*) FROM hits").fetchone()[0],
            "assets": con.execute("SELECT COUNT(*) FROM assets").fetchone()[0],
            "assets_with_name": con.execute(
                "SELECT COUNT(*) FROM assets WHERE name IS NOT NULL AND name != ''"
            ).fetchone()[0],
            "assets_with_market_cap": con.execute(
                "SELECT COUNT(*) FROM assets WHERE market_cap_usd IS NOT NULL"
            ).fetchone()[0],
            "catalysts": con.execute("SELECT COUNT(*) FROM catalysts").fetchone()[0],
        }
