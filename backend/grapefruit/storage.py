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
    """Idempotent DDL. The canonical schema also lives in supabase/migrations/0001_redesign.sql;
    this keeps local dev usable without needing to run the migration by hand."""
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
            CREATE TABLE IF NOT EXISTS app_state (
                key TEXT PRIMARY KEY,
                value JSONB NOT NULL,
                updated_at TIMESTAMPTZ NOT NULL
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS winners (
                id BIGSERIAL PRIMARY KEY,
                symbol TEXT NOT NULL,
                start_ts DATE NOT NULL,
                end_ts DATE NOT NULL,
                days_to_peak INTEGER NOT NULL,
                trough_price DOUBLE PRECISION NOT NULL,
                peak_price DOUBLE PRECISION NOT NULL,
                multiplier DOUBLE PRECISION NOT NULL,
                post_peak_retention DOUBLE PRECISION,
                breakout_ratio DOUBLE PRECISION,
                market_cap_usd_at_peak DOUBLE PRECISION,
                sector TEXT,
                industry TEXT,
                status TEXT NOT NULL CHECK (status IN ('held', 'faded')),
                detected_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                UNIQUE (symbol, end_ts)
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS winner_catalysts (
                winner_id BIGINT PRIMARY KEY REFERENCES winners(id) ON DELETE CASCADE,
                headline TEXT,
                summary TEXT,
                spike_explanation TEXT,
                was_foreseeable BOOLEAN,
                foreseeable_evidence TEXT,
                perplexity_citations JSONB,
                fetched_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS watchlist (
                symbol TEXT PRIMARY KEY,
                last_close DOUBLE PRECISION,
                market_cap_usd DOUBLE PRECISION,
                sector TEXT,
                industry TEXT,
                why_listed TEXT NOT NULL,
                added_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS upcoming_events (
                id BIGSERIAL PRIMARY KEY,
                symbol TEXT NOT NULL,
                event_ts DATE NOT NULL,
                event_type TEXT NOT NULL CHECK (event_type IN ('earnings', 'trial_phase3', 'other')),
                title TEXT,
                source TEXT,
                source_url TEXT,
                est_revenue DOUBLE PRECISION,
                est_eps DOUBLE PRECISION,
                fetched_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                UNIQUE (symbol, event_ts, event_type, title)
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS pipeline_runs (
                id BIGSERIAL PRIMARY KEY,
                job_name TEXT NOT NULL,
                started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                finished_at TIMESTAMPTZ,
                status TEXT NOT NULL CHECK (status IN ('running', 'done', 'error')),
                rows_processed INTEGER,
                error_msg TEXT
            )
            """
        )
        cur.execute("CREATE INDEX IF NOT EXISTS bars_symbol_idx ON bars(symbol)")
        cur.execute("CREATE INDEX IF NOT EXISTS winners_detected_idx ON winners(detected_at DESC)")
        cur.execute("CREATE INDEX IF NOT EXISTS winners_status_idx ON winners(status)")
        cur.execute("CREATE INDEX IF NOT EXISTS upcoming_events_symbol_idx ON upcoming_events(symbol)")
        cur.execute("CREATE INDEX IF NOT EXISTS upcoming_events_ts_idx ON upcoming_events(event_ts)")
        cur.execute("CREATE INDEX IF NOT EXISTS pipeline_runs_job_idx ON pipeline_runs(job_name, started_at DESC)")

        # FKs to assets(symbol) so PostgREST can embed `assets(name)` from the
        # winners / watchlist queries the frontend makes. See
        # supabase/migrations/0002_assets_fks.sql. assets is created above, so
        # the target exists; guarded by pg_constraint so re-runs are no-ops.
        cur.execute(
            """
            DO $$
            BEGIN
                IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'winners_symbol_fkey') THEN
                    ALTER TABLE winners ADD CONSTRAINT winners_symbol_fkey
                        FOREIGN KEY (symbol) REFERENCES assets(symbol) ON DELETE CASCADE;
                END IF;
                IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'watchlist_symbol_fkey') THEN
                    ALTER TABLE watchlist ADD CONSTRAINT watchlist_symbol_fkey
                        FOREIGN KEY (symbol) REFERENCES assets(symbol) ON DELETE CASCADE;
                END IF;
            END $$;
            """
        )


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


def symbols_needing_sector(limit: int = 400) -> list[str]:
    """Symbols that surface in the UI (winners or watchlist) but have no sector
    yet in `assets`. Used by refresh_sectors to scope the yfinance backfill."""
    with _cur() as cur:
        cur.execute(
            """
            SELECT a.symbol
            FROM assets a
            WHERE (a.sector IS NULL OR a.sector = '')
              AND a.symbol IN (
                  SELECT symbol FROM winners
                  UNION
                  SELECT symbol FROM watchlist
              )
            ORDER BY a.symbol
            LIMIT %s
            """,
            [limit],
        )
        return [r[0] for r in cur.fetchall()]


def update_asset_sector(symbol: str, *, sector: str | None, industry: str | None) -> None:
    with _cur() as cur:
        cur.execute(
            "UPDATE assets SET sector = %s, industry = %s WHERE symbol = %s",
            [sector, industry, symbol],
        )


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
# status
# ---------------------------------------------------------------------------

def counts() -> dict:
    with _cur() as cur:
        cur.execute("SELECT COUNT(DISTINCT symbol) FROM bars")
        bar_symbols = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM assets")
        assets = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM assets WHERE name IS NOT NULL AND name != ''")
        assets_with_name = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM assets WHERE market_cap_usd IS NOT NULL")
        assets_with_market_cap = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM winners")
        winners = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM winner_catalysts")
        winner_catalysts = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM watchlist")
        watchlist = cur.fetchone()[0]
        return {
            "bar_symbols": bar_symbols,
            "assets": assets,
            "assets_with_name": assets_with_name,
            "assets_with_market_cap": assets_with_market_cap,
            "winners": winners,
            "winner_catalysts": winner_catalysts,
            "watchlist": watchlist,
        }


# ---------------------------------------------------------------------------
# winners + winner_catalysts (Part 1 outputs)
# ---------------------------------------------------------------------------

def upsert_winner(row: dict) -> int:
    """Insert/update a detected steep-rise event and return its id."""
    cols = (
        "symbol", "start_ts", "end_ts", "days_to_peak",
        "trough_price", "peak_price", "multiplier",
        "post_peak_retention", "breakout_ratio",
        "market_cap_usd_at_peak", "sector", "industry", "status",
    )
    payload = tuple(row.get(c) for c in cols)
    with _cur() as cur:
        cur.execute(
            """
            INSERT INTO winners
                (symbol, start_ts, end_ts, days_to_peak,
                 trough_price, peak_price, multiplier,
                 post_peak_retention, breakout_ratio,
                 market_cap_usd_at_peak, sector, industry, status)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (symbol, end_ts) DO UPDATE SET
                start_ts = EXCLUDED.start_ts,
                days_to_peak = EXCLUDED.days_to_peak,
                trough_price = EXCLUDED.trough_price,
                peak_price = EXCLUDED.peak_price,
                multiplier = EXCLUDED.multiplier,
                post_peak_retention = EXCLUDED.post_peak_retention,
                breakout_ratio = EXCLUDED.breakout_ratio,
                market_cap_usd_at_peak = EXCLUDED.market_cap_usd_at_peak,
                sector = EXCLUDED.sector,
                industry = EXCLUDED.industry,
                status = EXCLUDED.status,
                detected_at = NOW()
            RETURNING id
            """,
            payload,
        )
        return cur.fetchone()[0]


def upsert_winner_catalyst(row: dict) -> None:
    cols = (
        "winner_id", "headline", "summary", "spike_explanation",
        "was_foreseeable", "foreseeable_evidence", "perplexity_citations",
    )
    payload = list(row.get(c) for c in cols)
    # Serialize JSONB
    if payload[-1] is not None and not isinstance(payload[-1], str):
        payload[-1] = json.dumps(payload[-1])
    with _cur() as cur:
        cur.execute(
            """
            INSERT INTO winner_catalysts
                (winner_id, headline, summary, spike_explanation,
                 was_foreseeable, foreseeable_evidence, perplexity_citations,
                 fetched_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, NOW())
            ON CONFLICT (winner_id) DO UPDATE SET
                headline = EXCLUDED.headline,
                summary = EXCLUDED.summary,
                spike_explanation = EXCLUDED.spike_explanation,
                was_foreseeable = EXCLUDED.was_foreseeable,
                foreseeable_evidence = EXCLUDED.foreseeable_evidence,
                perplexity_citations = EXCLUDED.perplexity_citations,
                fetched_at = NOW()
            """,
            payload,
        )


def winners_without_catalyst(limit: int | None = None) -> list[dict]:
    q = """
        SELECT w.id, w.symbol, w.start_ts, w.end_ts,
               w.trough_price, w.peak_price, w.multiplier,
               a.name
        FROM winners w
        LEFT JOIN winner_catalysts c ON c.winner_id = w.id
        LEFT JOIN assets a ON a.symbol = w.symbol
        WHERE c.winner_id IS NULL
        ORDER BY w.multiplier DESC
    """
    params: list = []
    if limit:
        q += " LIMIT %s"
        params.append(limit)
    with _cur(row_factory=dict_row) as cur:
        cur.execute(q, params)
        return [dict(r) for r in cur.fetchall()]


# ---------------------------------------------------------------------------
# watchlist (Part 2 candidates)
# ---------------------------------------------------------------------------

def upsert_watchlist_rows(rows: list[dict]) -> int:
    if not rows:
        return 0
    cols = ("symbol", "last_close", "market_cap_usd", "sector", "industry", "why_listed")
    payload = [tuple(r.get(c) for c in cols) for r in rows]
    with _cur() as cur:
        cur.executemany(
            """
            INSERT INTO watchlist
                (symbol, last_close, market_cap_usd, sector, industry, why_listed)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (symbol) DO UPDATE SET
                last_close = EXCLUDED.last_close,
                market_cap_usd = EXCLUDED.market_cap_usd,
                sector = EXCLUDED.sector,
                industry = EXCLUDED.industry,
                why_listed = EXCLUDED.why_listed,
                added_at = NOW()
            """,
            payload,
        )
    return len(payload)


def replace_watchlist(rows: list[dict]) -> int:
    """Atomically replace the entire watchlist with `rows`."""
    cols = ("symbol", "last_close", "market_cap_usd", "sector", "industry", "why_listed")
    payload = [tuple(r.get(c) for c in cols) for r in rows]
    with _conn() as con:
        with con.cursor() as cur:
            cur.execute("DELETE FROM watchlist")
            if payload:
                cur.executemany(
                    """
                    INSERT INTO watchlist
                        (symbol, last_close, market_cap_usd, sector, industry, why_listed)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    """,
                    payload,
                )
    return len(payload)


# ---------------------------------------------------------------------------
# upcoming_events (Part 2 forward-looking)
# ---------------------------------------------------------------------------

def upsert_upcoming_events(rows: list[dict]) -> int:
    if not rows:
        return 0
    cols = (
        "symbol", "event_ts", "event_type", "title",
        "source", "source_url", "est_revenue", "est_eps",
    )
    payload = [tuple(r.get(c) for c in cols) for r in rows]
    with _cur() as cur:
        cur.executemany(
            """
            INSERT INTO upcoming_events
                (symbol, event_ts, event_type, title, source, source_url, est_revenue, est_eps)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (symbol, event_ts, event_type, title) DO UPDATE SET
                source = EXCLUDED.source,
                source_url = EXCLUDED.source_url,
                est_revenue = EXCLUDED.est_revenue,
                est_eps = EXCLUDED.est_eps,
                fetched_at = NOW()
            """,
            payload,
        )
    return len(payload)


# ---------------------------------------------------------------------------
# pipeline_runs (observability)
# ---------------------------------------------------------------------------

def start_pipeline_run(job_name: str) -> int:
    with _cur() as cur:
        cur.execute(
            "INSERT INTO pipeline_runs (job_name, status) VALUES (%s, 'running') RETURNING id",
            [job_name],
        )
        return cur.fetchone()[0]


def finish_pipeline_run(run_id: int, *, rows_processed: int | None = None,
                        error: str | None = None) -> None:
    status = "error" if error else "done"
    with _cur() as cur:
        cur.execute(
            """
            UPDATE pipeline_runs
            SET finished_at = NOW(), status = %s, rows_processed = %s, error_msg = %s
            WHERE id = %s
            """,
            [status, rows_processed, error, run_id],
        )


# ---------------------------------------------------------------------------
# Helpers used by the pipeline orchestration
# ---------------------------------------------------------------------------

def latest_bar_date(symbol: str) -> date | None:
    """Most recent bar date for a symbol, or None if the symbol has no bars yet."""
    return last_ts(symbol)


def symbols_in_assets() -> list[str]:
    with _cur() as cur:
        cur.execute("SELECT symbol FROM assets ORDER BY symbol")
        return [r[0] for r in cur.fetchall()]


def assets_needing_fundamentals(stale_after_days: int = 7) -> list[str]:
    """Symbols whose `assets.refreshed_at` is older than `stale_after_days` (or null)."""
    with _cur() as cur:
        cur.execute(
            """
            SELECT symbol FROM assets
            WHERE refreshed_at IS NULL
               OR refreshed_at < NOW() - (%s::int * INTERVAL '1 day')
            ORDER BY symbol
            """,
            [stale_after_days],
        )
        return [r[0] for r in cur.fetchall()]
