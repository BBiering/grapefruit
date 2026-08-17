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
    """Idempotent DDL. 7 tables: bars, assets, app_state, forward_catalysts,
    pipeline_runs, step_change_history, step_change_catalysts."""
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
            CREATE TABLE IF NOT EXISTS forward_catalysts (
                symbol TEXT PRIMARY KEY REFERENCES assets(symbol) ON DELETE CASCADE,
                detected BOOLEAN,
                event_name TEXT,
                impact_type TEXT,
                expected_window TEXT,
                strategic_summary TEXT,
                source_url TEXT,
                model TEXT,
                confidence TEXT,
                expected_impact_pct DOUBLE PRECISION,
                scanned_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """
        )
        cur.execute("ALTER TABLE forward_catalysts ADD COLUMN IF NOT EXISTS confidence TEXT")
        cur.execute("ALTER TABLE forward_catalysts ADD COLUMN IF NOT EXISTS expected_impact_pct DOUBLE PRECISION")
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
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS step_change_history (
                id BIGSERIAL PRIMARY KEY,
                symbol TEXT NOT NULL REFERENCES assets(symbol) ON DELETE CASCADE,
                start_ts DATE NOT NULL,
                end_ts DATE NOT NULL,
                days_to_peak INTEGER NOT NULL,
                trough_price DOUBLE PRECISION NOT NULL,
                peak_price DOUBLE PRECISION NOT NULL,
                multiplier DOUBLE PRECISION NOT NULL,
                post_peak_retention DOUBLE PRECISION,
                breakout_ratio DOUBLE PRECISION,
                market_cap_usd_at_peak DOUBLE PRECISION,
                status TEXT CHECK (status IN ('held', 'faded')),
                tier TEXT CHECK (tier IN ('major',)),
                detected_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                UNIQUE (symbol, end_ts)
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS step_change_catalysts (
                step_change_id BIGINT PRIMARY KEY REFERENCES step_change_history(id) ON DELETE CASCADE,
                headline TEXT,
                summary TEXT,
                spike_explanation TEXT,
                was_foreseeable BOOLEAN,
                foreseeable_evidence TEXT,
                perplexity_citations JSONB,
                model TEXT,
                fetched_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """
        )

        # Indexes
        cur.execute("CREATE INDEX IF NOT EXISTS bars_symbol_idx ON bars(symbol)")
        cur.execute("CREATE INDEX IF NOT EXISTS pipeline_runs_job_idx ON pipeline_runs(job_name, started_at DESC)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_step_change_symbol ON step_change_history(symbol)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_step_change_end_ts ON step_change_history(end_ts DESC)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_step_change_multiplier ON step_change_history(multiplier DESC)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_step_change_tier ON step_change_history(tier)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_forward_catalysts_confidence ON forward_catalysts(confidence)")

        # Drop legacy tables if they still exist
        for legacy in ("winners", "winner_catalysts", "watchlist", "watchlist_moves",
                        "company_metrics", "upcoming_events"):
            cur.execute(f"DROP TABLE IF EXISTS {legacy} CASCADE")


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


# momentum_180d_all() removed - momentum no longer used in screening strategy


def load_assets_map() -> dict[str, dict]:
    """All assets keyed by symbol: {symbol: {name, exchange, sector, industry, market_cap_usd}}."""
    with _cur(row_factory=dict_row) as cur:
        cur.execute(
            "SELECT symbol, name, exchange, sector, industry, market_cap_usd FROM assets"
        )
        return {r["symbol"]: dict(r) for r in cur.fetchall()}


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
    """All symbols in `assets` that have no sector yet. Used by refresh_sectors
    to backfill sector/industry data for the full universe."""
    with _cur() as cur:
        cur.execute(
            """
            SELECT a.symbol
            FROM assets a
            WHERE (a.sector IS NULL OR a.sector = '')
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


_FORWARD_CATALYST_COLS = (
    "symbol", "detected", "event_name", "impact_type", "expected_window",
    "strategic_summary", "source_url", "model", "confidence", "expected_impact_pct",
)


def replace_forward_catalysts(rows: list[dict]) -> int:
    """Atomically replace forward_catalysts with `rows` (one per symbol)."""
    payload = [tuple(r.get(c) for c in _FORWARD_CATALYST_COLS) for r in rows]
    placeholders = ", ".join(["%s"] * len(_FORWARD_CATALYST_COLS))
    collist = ", ".join(_FORWARD_CATALYST_COLS)
    with _conn() as con:
        with con.cursor() as cur:
            cur.execute("DELETE FROM forward_catalysts")
            if payload:
                cur.executemany(
                    f"INSERT INTO forward_catalysts ({collist}) VALUES ({placeholders})",
                    payload,
                )
    return len(payload)


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


# ---------------------------------------------------------------------------
# step_change_history
# ---------------------------------------------------------------------------

def upsert_step_change(row: dict) -> int:
    """Insert or update a step change event. Returns the step_change_id.

    Expected keys: symbol, start_ts, end_ts, days_to_peak, trough_price, peak_price,
                   multiplier, post_peak_retention, breakout_ratio, market_cap_usd_at_peak,
                   status, tier
    """
    with _cur() as cur:
        cur.execute(
            """
            INSERT INTO step_change_history (
                symbol, start_ts, end_ts, days_to_peak,
                trough_price, peak_price, multiplier,
                post_peak_retention, breakout_ratio, market_cap_usd_at_peak,
                status, tier, detected_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
            ON CONFLICT (symbol, end_ts) DO UPDATE SET
                start_ts = EXCLUDED.start_ts,
                days_to_peak = EXCLUDED.days_to_peak,
                trough_price = EXCLUDED.trough_price,
                peak_price = EXCLUDED.peak_price,
                multiplier = EXCLUDED.multiplier,
                post_peak_retention = EXCLUDED.post_peak_retention,
                breakout_ratio = EXCLUDED.breakout_ratio,
                market_cap_usd_at_peak = EXCLUDED.market_cap_usd_at_peak,
                status = EXCLUDED.status,
                tier = EXCLUDED.tier,
                detected_at = EXCLUDED.detected_at
            RETURNING id
            """,
            [
                row["symbol"],
                row["start_ts"],
                row["end_ts"],
                row["days_to_peak"],
                row["trough_price"],
                row["peak_price"],
                row["multiplier"],
                row.get("post_peak_retention"),
                row.get("breakout_ratio"),
                row.get("market_cap_usd_at_peak"),
                row["status"],
                row["tier"],
            ],
        )
        result = cur.fetchone()
        return result[0] if result else -1


def load_step_changes(tier: str | None = None, min_multiplier: float | None = None) -> list[dict]:
    """Load step change events with optional filtering."""
    query = """
        SELECT id, symbol, start_ts, end_ts, days_to_peak,
               trough_price, peak_price, multiplier,
               post_peak_retention, breakout_ratio, market_cap_usd_at_peak,
               status, tier, detected_at
        FROM step_change_history
        WHERE 1=1
    """
    params = []
    if tier:
        query += " AND tier = %s"
        params.append(tier)
    if min_multiplier:
        query += " AND multiplier >= %s"
        params.append(min_multiplier)
    query += " ORDER BY multiplier DESC"

    with _cur(row_factory=dict_row) as cur:
        cur.execute(query, params)
        return cur.fetchall()


def load_step_changes_for_symbol(symbol: str) -> list[dict]:
    """Load all step changes for a specific symbol."""
    with _cur(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT id, symbol, start_ts, end_ts, days_to_peak,
                   trough_price, peak_price, multiplier,
                   post_peak_retention, breakout_ratio, market_cap_usd_at_peak,
                   status, tier, detected_at
            FROM step_change_history
            WHERE symbol = %s
            ORDER BY end_ts DESC
            """,
            [symbol],
        )
        return cur.fetchall()


# ---------------------------------------------------------------------------
# step_change_catalysts (NEW - explanations for step changes)
# ---------------------------------------------------------------------------

def upsert_step_change_catalyst(row: dict) -> None:
    """Insert or update catalyst explanation for a step change event.

    Expected keys: step_change_id, headline, summary, spike_explanation,
                   was_foreseeable, foreseeable_evidence, perplexity_citations, model
    """
    with _cur() as cur:
        cur.execute(
            """
            INSERT INTO step_change_catalysts (
                step_change_id, headline, summary, spike_explanation,
                was_foreseeable, foreseeable_evidence, perplexity_citations, model, fetched_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW())
            ON CONFLICT (step_change_id) DO UPDATE SET
                headline = EXCLUDED.headline,
                summary = EXCLUDED.summary,
                spike_explanation = EXCLUDED.spike_explanation,
                was_foreseeable = EXCLUDED.was_foreseeable,
                foreseeable_evidence = EXCLUDED.foreseeable_evidence,
                perplexity_citations = EXCLUDED.perplexity_citations,
                model = EXCLUDED.model,
                fetched_at = EXCLUDED.fetched_at
            """,
            [
                row["step_change_id"],
                row.get("headline"),
                row.get("summary"),
                row.get("spike_explanation"),
                row.get("was_foreseeable"),
                row.get("foreseeable_evidence"),
                json.dumps(row.get("perplexity_citations")) if row.get("perplexity_citations") else None,
                row.get("model", "sonar-pro"),
            ],
        )


def load_step_change_catalysts() -> list[dict]:
    """Load all step change catalysts."""
    with _cur(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT step_change_id, headline, summary, spike_explanation,
                   was_foreseeable, foreseeable_evidence, perplexity_citations, model, fetched_at
            FROM step_change_catalysts
            ORDER BY fetched_at DESC
            """
        )
        return cur.fetchall()


def load_unexplained_step_changes(tier: str = "major", limit: int = 250) -> list[dict]:
    """Load step changes that don't have catalyst explanations yet.

    Prioritizes by tier (major first) → recency → never-explained.
    """
    with _cur(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT h.id, h.symbol, h.start_ts, h.end_ts, h.multiplier, h.tier
            FROM step_change_history h
            LEFT JOIN step_change_catalysts c ON c.step_change_id = h.id
            WHERE c.step_change_id IS NULL
            ORDER BY
                CASE h.tier
                    WHEN 'major' THEN 1
                    WHEN 'moderate' THEN 2
                    WHEN 'minor' THEN 3
                    ELSE 4
                END,
                h.end_ts DESC
            LIMIT %s
            """,
            [limit],
        )
        return cur.fetchall()


# ---------------------------------------------------------------------------
# maintenance
# ---------------------------------------------------------------------------

def cleanup_symbols_by_exchange(exchange: str) -> dict[str, int]:
    """Delete all rows for symbols ending in `.{exchange}` from assets
    (cascades to tables with FK) and from bars (no FK cascade).
    Returns counts of deleted rows per table."""
    pattern = f"%.{exchange}"
    with _conn() as con:
        with con.cursor() as cur:
            cur.execute("DELETE FROM bars WHERE symbol LIKE %s", [pattern])
            bars_deleted = cur.rowcount
            cur.execute("DELETE FROM assets WHERE symbol LIKE %s", [pattern])
            assets_deleted = cur.rowcount
    return {"assets": assets_deleted, "bars": bars_deleted}
