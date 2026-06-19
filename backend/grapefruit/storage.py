"""Postgres-backed storage layer (Supabase). Public API matches the prior
DuckDB-backed module so the rest of the codebase doesn't need changes.

DDL is idempotent in init_db(); no migration tooling.
"""
from __future__ import annotations

import json
import threading
from contextlib import contextmanager
from datetime import date, datetime, timezone
from typing import Any

import pandas as pd
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from grapefruit.config import settings


_pool_lock = threading.Lock()
_pool: ConnectionPool | None = None


def _get_pool() -> ConnectionPool:
    global _pool
    with _pool_lock:
        if _pool is None:
            if not settings.database_url:
                raise RuntimeError(
                    "DATABASE_URL is not set. Add it to .env (Supabase connection string)."
                )
            _pool = ConnectionPool(
                conninfo=settings.database_url,
                min_size=1,
                max_size=10,
                kwargs={"autocommit": True},
            )
        return _pool


@contextmanager
def _conn():
    pool = _get_pool()
    with pool.connection() as con:
        yield con


@contextmanager
def _cur(row_factory=None):
    with _conn() as con:
        with con.cursor(row_factory=row_factory) as cur:
            yield cur


def init_db() -> None:
    with _cur() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS bars (
                symbol TEXT NOT NULL,
                ts DATE NOT NULL,
                open DOUBLE PRECISION,
                high DOUBLE PRECISION,
                low DOUBLE PRECISION,
                close DOUBLE PRECISION,
                volume BIGINT,
                PRIMARY KEY (symbol, ts)
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS hits (
                symbol TEXT NOT NULL,
                window_days INTEGER NOT NULL,
                threshold DOUBLE PRECISION NOT NULL,
                start_ts DATE NOT NULL,
                end_ts DATE NOT NULL,
                trough_price DOUBLE PRECISION,
                peak_price DOUBLE PRECISION,
                multiplier DOUBLE PRECISION,
                scanned_at TIMESTAMPTZ
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS assets (
                symbol TEXT PRIMARY KEY,
                name TEXT,
                exchange TEXT,
                sector TEXT,
                industry TEXT,
                market_cap_usd DOUBLE PRECISION,
                refreshed_at TIMESTAMPTZ
            )
            """
        )
        cur.execute("ALTER TABLE assets ADD COLUMN IF NOT EXISTS market_cap_usd DOUBLE PRECISION")
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS catalysts (
                symbol TEXT NOT NULL,
                end_ts DATE NOT NULL,
                headline TEXT,
                summary TEXT,
                spike_explanation TEXT,
                was_foreseeable BOOLEAN,
                foreseeable_evidence TEXT,
                fetched_at TIMESTAMPTZ,
                PRIMARY KEY (symbol, end_ts)
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS app_state (
                key TEXT PRIMARY KEY,
                value JSONB NOT NULL,
                updated_at TIMESTAMPTZ NOT NULL
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS news_cache (
                symbol TEXT NOT NULL,
                around DATE NOT NULL,
                days INTEGER NOT NULL,
                articles JSONB NOT NULL,
                fetched_at TIMESTAMPTZ NOT NULL,
                PRIMARY KEY (symbol, around, days)
            )
            """
        )
        cur.execute("CREATE INDEX IF NOT EXISTS bars_symbol_idx ON bars(symbol)")
        cur.execute("CREATE INDEX IF NOT EXISTS hits_window_idx ON hits(window_days)")
        cur.execute("CREATE INDEX IF NOT EXISTS catalysts_symbol_idx ON catalysts(symbol)")


# ---------------------------------------------------------------------------
# bars
# ---------------------------------------------------------------------------

def upsert_bars(df: pd.DataFrame) -> int:
    if df.empty:
        return 0
    cols = ["symbol", "ts", "open", "high", "low", "close", "volume"]
    rows = [tuple(r) for r in df[cols].itertuples(index=False, name=None)]
    with _cur() as cur:
        cur.executemany(
            """
            INSERT INTO bars (symbol, ts, open, high, low, close, volume)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (symbol, ts) DO UPDATE SET
                open = EXCLUDED.open,
                high = EXCLUDED.high,
                low = EXCLUDED.low,
                close = EXCLUDED.close,
                volume = EXCLUDED.volume
            """,
            rows,
        )
    return len(rows)


def load_symbol(symbol: str, start: date | None = None, end: date | None = None) -> pd.DataFrame:
    q = "SELECT ts, open, high, low, close, volume FROM bars WHERE symbol = %s"
    params: list[Any] = [symbol]
    if start:
        q += " AND ts >= %s"
        params.append(start)
    if end:
        q += " AND ts <= %s"
        params.append(end)
    q += " ORDER BY ts"
    with _cur() as cur:
        cur.execute(q, params)
        rows = cur.fetchall()
    return pd.DataFrame(rows, columns=["ts", "open", "high", "low", "close", "volume"])


def last_ts(symbol: str) -> date | None:
    with _cur() as cur:
        cur.execute("SELECT MAX(ts) FROM bars WHERE symbol = %s", [symbol])
        row = cur.fetchone()
        return row[0] if row and row[0] else None


def symbols_with_bars() -> list[str]:
    with _cur() as cur:
        cur.execute("SELECT DISTINCT symbol FROM bars ORDER BY symbol")
        return [r[0] for r in cur.fetchall()]


# ---------------------------------------------------------------------------
# hits
# ---------------------------------------------------------------------------

def hit_symbols_missing_metadata() -> list[str]:
    with _cur() as cur:
        cur.execute(
            """
            SELECT DISTINCT h.symbol
            FROM hits h
            LEFT JOIN assets a ON a.symbol = h.symbol
            WHERE a.name IS NULL OR a.name = ''
            ORDER BY h.symbol
            """
        )
        return [r[0] for r in cur.fetchall()]


def save_hits(rows: list[dict], window_days: int, threshold: float) -> None:
    if not rows:
        return
    scanned_at = datetime.now(timezone.utc)
    payload = [
        (
            r["symbol"],
            window_days,
            threshold,
            r["start_ts"],
            r["end_ts"],
            r["trough_price"],
            r["peak_price"],
            r["multiplier"],
            scanned_at,
        )
        for r in rows
    ]
    with _conn() as con:
        with con.cursor() as cur:
            cur.execute(
                "DELETE FROM hits WHERE window_days = %s AND threshold = %s",
                [window_days, threshold],
            )
            cur.executemany(
                """
                INSERT INTO hits
                    (symbol, window_days, threshold, start_ts, end_ts,
                     trough_price, peak_price, multiplier, scanned_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                payload,
            )


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
             AND b.ts >= h.start_ts - (%s::int * INTERVAL '1 day')
            GROUP BY h.symbol, h.start_ts, h.end_ts
        )
        SELECT
            h.symbol, h.window_days, h.threshold,
            h.start_ts, h.end_ts,
            h.trough_price, h.peak_price, h.multiplier, h.scanned_at,
            a.name, a.exchange, a.sector, a.industry, a.market_cap_usd,
            l.current_price, l.last_ts,
            CASE WHEN l.last_ts IS NULL THEN NULL
                 ELSE (l.last_ts - h.end_ts)::int
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
    params: list[Any] = [pre_trough_lookback_days]
    if window_weeks is not None:
        q += " AND h.window_days = %s"
        params.append(window_weeks * 5)
    if min_multiplier is not None:
        q += " AND h.multiplier >= %s"
        params.append(min_multiplier)
    if max_days_since_peak is not None:
        q += " AND (l.last_ts - h.end_ts)::int <= %s"
        params.append(max_days_since_peak)
    if min_peak_retention is not None:
        q += " AND (h.peak_price > 0 AND l.current_price / h.peak_price >= %s)"
        params.append(min_peak_retention)
    if min_breakout_ratio is not None:
        q += (
            " AND (p.pre_high IS NULL OR p.pre_high <= 0"
            "      OR h.peak_price / p.pre_high >= %s)"
        )
        params.append(min_breakout_ratio)
    if industry is not None:
        q += " AND a.industry = %s"
        params.append(industry)
    q += " ORDER BY h.multiplier DESC"
    with _cur(row_factory=dict_row) as cur:
        cur.execute(q, params)
        return [dict(r) for r in cur.fetchall()]


# ---------------------------------------------------------------------------
# assets
# ---------------------------------------------------------------------------

_ASSET_COLS = ("symbol", "name", "exchange", "sector", "industry", "market_cap_usd", "refreshed_at")


def upsert_asset(row: dict) -> None:
    payload = tuple(row.get(col) for col in _ASSET_COLS)
    with _cur() as cur:
        cur.execute(
            """
            INSERT INTO assets (symbol, name, exchange, sector, industry, market_cap_usd, refreshed_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (symbol) DO UPDATE SET
                name = EXCLUDED.name,
                exchange = EXCLUDED.exchange,
                sector = EXCLUDED.sector,
                industry = EXCLUDED.industry,
                market_cap_usd = EXCLUDED.market_cap_usd,
                refreshed_at = EXCLUDED.refreshed_at
            """,
            payload,
        )


def upsert_assets(rows: list[dict]) -> int:
    if not rows:
        return 0
    payload = [tuple(r.get(col) for col in _ASSET_COLS) for r in rows]
    with _cur() as cur:
        cur.executemany(
            """
            INSERT INTO assets (symbol, name, exchange, sector, industry, market_cap_usd, refreshed_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (symbol) DO UPDATE SET
                name = EXCLUDED.name,
                exchange = EXCLUDED.exchange,
                sector = EXCLUDED.sector,
                industry = EXCLUDED.industry,
                market_cap_usd = EXCLUDED.market_cap_usd,
                refreshed_at = EXCLUDED.refreshed_at
            """,
            payload,
        )
    return len(payload)


def load_asset(symbol: str) -> dict | None:
    with _cur(row_factory=dict_row) as cur:
        cur.execute(
            "SELECT symbol, name, exchange, sector, industry, market_cap_usd, refreshed_at FROM assets WHERE symbol = %s",
            [symbol],
        )
        row = cur.fetchone()
        return dict(row) if row else None


def symbols_with_market_cap_below(cap_usd: float) -> list[str]:
    with _cur() as cur:
        cur.execute(
            "SELECT symbol FROM assets WHERE market_cap_usd IS NOT NULL AND market_cap_usd > 0 AND market_cap_usd <= %s",
            [cap_usd],
        )
        return [r[0] for r in cur.fetchall()]


def symbols_with_last_close_below(price_usd: float) -> list[str]:
    with _cur() as cur:
        cur.execute(
            """
            WITH latest AS (
                SELECT b.symbol, b.close FROM bars b
                JOIN (SELECT symbol, MAX(ts) AS mx FROM bars GROUP BY symbol) m
                  ON m.symbol = b.symbol AND m.mx = b.ts
            )
            SELECT symbol FROM latest WHERE close > 0 AND close <= %s
            """,
            [price_usd],
        )
        return [r[0] for r in cur.fetchall()]


# ---------------------------------------------------------------------------
# catalysts
# ---------------------------------------------------------------------------

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
    payload = tuple(row.get(col) for col in _CATALYST_COLS)
    with _cur() as cur:
        cur.execute(
            """
            INSERT INTO catalysts
                (symbol, end_ts, headline, summary, spike_explanation,
                 was_foreseeable, foreseeable_evidence, fetched_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (symbol, end_ts) DO UPDATE SET
                headline = EXCLUDED.headline,
                summary = EXCLUDED.summary,
                spike_explanation = EXCLUDED.spike_explanation,
                was_foreseeable = EXCLUDED.was_foreseeable,
                foreseeable_evidence = EXCLUDED.foreseeable_evidence,
                fetched_at = EXCLUDED.fetched_at
            """,
            payload,
        )


def load_catalyst(symbol: str, end_ts: date) -> dict | None:
    with _cur(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT symbol, end_ts, headline, summary, spike_explanation,
                   was_foreseeable, foreseeable_evidence, fetched_at
            FROM catalysts WHERE symbol = %s AND end_ts = %s
            """,
            [symbol, end_ts],
        )
        row = cur.fetchone()
        return dict(row) if row else None


def hits_without_catalyst(limit: int | None = None) -> list[dict]:
    q = """
        SELECT h.symbol, h.start_ts, h.end_ts, h.trough_price, h.peak_price, h.multiplier
        FROM hits h
        LEFT JOIN catalysts c ON c.symbol = h.symbol AND c.end_ts = h.end_ts
        WHERE c.symbol IS NULL
        ORDER BY h.multiplier DESC
    """
    params: list[Any] = []
    if limit:
        q += " LIMIT %s"
        params.append(limit)
    with _cur(row_factory=dict_row) as cur:
        cur.execute(q, params)
        return [dict(r) for r in cur.fetchall()]


def list_hit_industries() -> list[str]:
    with _cur() as cur:
        cur.execute(
            """
            SELECT DISTINCT a.industry
            FROM hits h JOIN assets a ON a.symbol = h.symbol
            WHERE a.industry IS NOT NULL AND a.industry != ''
            ORDER BY a.industry
            """
        )
        return [r[0] for r in cur.fetchall()]


# ---------------------------------------------------------------------------
# misc state (replaces data/universe.json)
# ---------------------------------------------------------------------------

def set_app_state(key: str, value: dict) -> None:
    with _cur() as cur:
        cur.execute(
            """
            INSERT INTO app_state (key, value, updated_at)
            VALUES (%s, %s::jsonb, %s)
            ON CONFLICT (key) DO UPDATE SET
                value = EXCLUDED.value,
                updated_at = EXCLUDED.updated_at
            """,
            [key, json.dumps(value), datetime.now(timezone.utc)],
        )


def get_app_state(key: str) -> dict | None:
    with _cur() as cur:
        cur.execute("SELECT value FROM app_state WHERE key = %s", [key])
        row = cur.fetchone()
        return row[0] if row else None


# ---------------------------------------------------------------------------
# news cache (replaces data/news_cache/*.json)
# ---------------------------------------------------------------------------

def load_news(symbol: str, around: date, days: int) -> list[dict] | None:
    with _cur() as cur:
        cur.execute(
            "SELECT articles FROM news_cache WHERE symbol = %s AND around = %s AND days = %s",
            [symbol, around, days],
        )
        row = cur.fetchone()
        return row[0] if row else None


def upsert_news(symbol: str, around: date, days: int, articles: list[dict]) -> None:
    with _cur() as cur:
        cur.execute(
            """
            INSERT INTO news_cache (symbol, around, days, articles, fetched_at)
            VALUES (%s, %s, %s, %s::jsonb, %s)
            ON CONFLICT (symbol, around, days) DO UPDATE SET
                articles = EXCLUDED.articles,
                fetched_at = EXCLUDED.fetched_at
            """,
            [symbol, around, days, json.dumps(articles), datetime.now(timezone.utc)],
        )


# ---------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------

def counts() -> dict:
    with _cur() as cur:
        cur.execute("SELECT COUNT(DISTINCT symbol) FROM bars")
        bar_symbols = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM hits")
        hits = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM assets")
        assets = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM assets WHERE name IS NOT NULL AND name != ''")
        assets_with_name = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM assets WHERE market_cap_usd IS NOT NULL")
        assets_with_market_cap = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM catalysts")
        catalysts = cur.fetchone()[0]
        return {
            "bar_symbols": bar_symbols,
            "hits": hits,
            "assets": assets,
            "assets_with_name": assets_with_name,
            "assets_with_market_cap": assets_with_market_cap,
            "catalysts": catalysts,
        }
