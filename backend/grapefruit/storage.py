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
        # Look-ahead screener score columns (see migration 0003_lookahead.sql).
        # Note: momentum_180d and momentum_score removed from screening strategy
        for col in (
            "dollar_volume", "quality_score",
            "insider_score", "combined_score", "net_income", "profit_margin",
        ):
            cur.execute(f"ALTER TABLE watchlist ADD COLUMN IF NOT EXISTS {col} DOUBLE PRECISION")
        cur.execute("ALTER TABLE watchlist ADD COLUMN IF NOT EXISTS rank INTEGER")
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS forward_catalysts (
                symbol TEXT PRIMARY KEY,
                detected BOOLEAN,
                event_name TEXT,
                impact_type TEXT,
                expected_window TEXT,
                strategic_summary TEXT,
                source_url TEXT,
                model TEXT,
                scanned_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
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
        # New universe-wide tables (migration 0007)
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS company_metrics (
                symbol TEXT PRIMARY KEY REFERENCES assets(symbol) ON DELETE CASCADE,
                quality_score DOUBLE PRECISION,
                net_income DOUBLE PRECISION,
                profit_margin DOUBLE PRECISION,
                revenue_ttm DOUBLE PRECISION,
                insider_score DOUBLE PRECISION,
                insider_net_value DOUBLE PRECISION,
                roe DOUBLE PRECISION,
                debt_to_equity DOUBLE PRECISION,
                current_ratio DOUBLE PRECISION,
                fetched_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                data_as_of DATE
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
                tier TEXT CHECK (tier IN ('major', 'moderate', 'minor')),
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

        cur.execute("CREATE INDEX IF NOT EXISTS bars_symbol_idx ON bars(symbol)")
        cur.execute("CREATE INDEX IF NOT EXISTS winners_detected_idx ON winners(detected_at DESC)")
        cur.execute("CREATE INDEX IF NOT EXISTS winners_status_idx ON winners(status)")
        cur.execute("CREATE INDEX IF NOT EXISTS upcoming_events_symbol_idx ON upcoming_events(symbol)")
        cur.execute("CREATE INDEX IF NOT EXISTS upcoming_events_ts_idx ON upcoming_events(event_ts)")
        cur.execute("CREATE INDEX IF NOT EXISTS pipeline_runs_job_idx ON pipeline_runs(job_name, started_at DESC)")

        # New table indexes
        cur.execute("CREATE INDEX IF NOT EXISTS idx_company_metrics_quality ON company_metrics(quality_score DESC)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_company_metrics_insider ON company_metrics(insider_score DESC)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_step_change_symbol ON step_change_history(symbol)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_step_change_end_ts ON step_change_history(end_ts DESC)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_step_change_multiplier ON step_change_history(multiplier DESC)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_step_change_tier ON step_change_history(tier)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_step_change_catalysts_foreseeable ON step_change_catalysts(was_foreseeable)")

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
                IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'forward_catalysts_symbol_fkey') THEN
                    ALTER TABLE forward_catalysts ADD CONSTRAINT forward_catalysts_symbol_fkey
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


def symbols_by_sector(sectors: list[str]) -> list[dict]:
    """Returns symbols with their metadata filtered by sector."""
    with _cur(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT
                a.symbol,
                a.name,
                a.sector,
                a.industry,
                a.market_cap_usd,
                b.close as last_close
            FROM assets a
            LEFT JOIN LATERAL (
                SELECT close FROM bars
                WHERE symbol = a.symbol
                ORDER BY ts DESC
                LIMIT 1
            ) b ON true
            WHERE a.sector = ANY(%s)
            ORDER BY a.market_cap_usd DESC NULLS LAST
            """,
            [sectors],
        )
        return [dict(r) for r in cur.fetchall()]


def upsert_risk_flags(flags: list[dict]) -> int:
    """Upsert risk flags for stocks to exclude from universe."""
    if not flags:
        return 0
    with _conn() as con:
        with con.cursor() as cur:
            cur.executemany(
                """
                INSERT INTO universe_risk_flags
                    (symbol, flag_type, flag_date, scheduled_date, split_ratio, description)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (symbol) DO UPDATE SET
                    flag_type = EXCLUDED.flag_type,
                    flag_date = EXCLUDED.flag_date,
                    scheduled_date = EXCLUDED.scheduled_date,
                    split_ratio = EXCLUDED.split_ratio,
                    description = EXCLUDED.description,
                    detected_at = NOW()
                """,
                [
                    (
                        f["symbol"],
                        f["flag_type"],
                        f["flag_date"],
                        f.get("scheduled_date"),
                        f.get("split_ratio"),
                        f.get("description"),
                    )
                    for f in flags
                ],
            )
    return len(flags)


def symbols_with_active_risk_flags() -> set[str]:
    """Returns set of symbols with active risk flags (for universe exclusion)."""
    with _cur() as cur:
        cur.execute("SELECT symbol FROM universe_risk_flags")
        return {r[0] for r in cur.fetchall()}


def top_symbols_by_market_cap(limit: int = 300) -> list[dict]:
    """Returns top N symbols by market cap with metadata."""
    with _cur(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT
                a.symbol,
                a.name,
                a.sector,
                a.industry,
                a.market_cap_usd,
                b.close as last_close
            FROM assets a
            LEFT JOIN LATERAL (
                SELECT close FROM bars
                WHERE symbol = a.symbol
                ORDER BY ts DESC
                LIMIT 1
            ) b ON true
            WHERE a.market_cap_usd IS NOT NULL AND a.market_cap_usd > 0
            ORDER BY a.market_cap_usd DESC
            LIMIT %s
            """,
            [limit],
        )
        return [dict(r) for r in cur.fetchall()]


def prioritize_for_catalyst_scan(
    sectors: list[str] | None = None,
    tier: int | None = None,
    limit: int = 200,
    stale_after_days: int = 7,
) -> list[dict]:
    """Returns stocks prioritized for catalyst scanning.

    Priority order:
    1. Never scanned (forward_catalysts.last_verified_at IS NULL)
    2. Approaching events (event_date within 14 days, needs re-verification)
    3. Stale scans (last_verified_at older than stale_after_days)

    Args:
        sectors: Filter by sectors (e.g., ["Biotechnology", "Pharmaceuticals"])
        tier: Filter by catalyst tier (1, 2, or 3) - None means no tier filter
        limit: Max number of stocks to return
        stale_after_days: Consider scans older than this many days as stale

    Returns:
        List of stocks with symbol, name, sector, last_close, last_verified_at, event_date
    """
    with _cur(row_factory=dict_row) as cur:
        # Build filters
        sector_filter = "AND a.sector = ANY(%s)" if sectors else ""
        tier_filter = "AND (fc.tier = %s OR fc.tier IS NULL)" if tier is not None else ""

        # Build parameter list dynamically
        params = []
        if sectors:
            params.append(sectors)
        if tier is not None:
            params.append(tier)
        params.extend([stale_after_days, limit])

        cur.execute(f"""
            SELECT
                a.symbol,
                a.name,
                a.sector,
                a.industry,
                a.market_cap_usd,
                b.close as last_close,
                fc.last_verified_at,
                fc.event_date,
                fc.tier
            FROM assets a
            LEFT JOIN LATERAL (
                SELECT close FROM bars WHERE symbol = a.symbol ORDER BY ts DESC LIMIT 1
            ) b ON true
            LEFT JOIN forward_catalysts fc ON fc.symbol = a.symbol
            WHERE 1=1 {sector_filter} {tier_filter}
              AND (
                  -- Never scanned (highest priority)
                  fc.last_verified_at IS NULL
                  OR
                  -- Approaching event date (needs re-verification)
                  (fc.event_date IS NOT NULL AND fc.event_date BETWEEN CURRENT_DATE AND CURRENT_DATE + 14)
                  OR
                  -- Stale scan (last verified more than N days ago)
                  fc.last_verified_at < NOW() - (%s::int * INTERVAL '1 day')
              )
            ORDER BY
                CASE
                    WHEN fc.last_verified_at IS NULL THEN 1  -- Never scanned first
                    WHEN fc.event_date BETWEEN CURRENT_DATE AND CURRENT_DATE + 14 THEN 2  -- Approaching events second
                    ELSE 3  -- Stale scans last
                END,
                fc.last_verified_at ASC NULLS FIRST,
                a.market_cap_usd DESC NULLS LAST
            LIMIT %s
        """, params)
        return [dict(r) for r in cur.fetchall()]


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


_WATCHLIST_COLS = (
    "symbol", "last_close", "market_cap_usd", "sector", "industry", "why_listed",
    "dollar_volume", "quality_score",
    "insider_score", "combined_score", "net_income", "profit_margin", "rank",
)


def replace_watchlist(rows: list[dict]) -> int:
    """Atomically replace the entire watchlist with `rows`."""
    payload = [tuple(r.get(c) for c in _WATCHLIST_COLS) for r in rows]
    placeholders = ", ".join(["%s"] * len(_WATCHLIST_COLS))
    collist = ", ".join(_WATCHLIST_COLS)
    with _conn() as con:
        with con.cursor() as cur:
            cur.execute("DELETE FROM watchlist")
            if payload:
                cur.executemany(
                    f"INSERT INTO watchlist ({collist}) VALUES ({placeholders})",
                    payload,
                )
    return len(payload)


_FORWARD_CATALYST_COLS = (
    "symbol", "detected", "event_name", "impact_type", "expected_window",
    "strategic_summary", "source_url", "model",
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


def watchlist_symbols() -> list[dict]:
    """Current watchlist rows the forward scan needs: symbol, last_close, name."""
    with _cur(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT w.symbol, w.last_close, a.name
            FROM watchlist w
            LEFT JOIN assets a ON a.symbol = w.symbol
            ORDER BY w.combined_score DESC NULLS LAST
            """
        )
        return [dict(r) for r in cur.fetchall()]


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


# ---------------------------------------------------------------------------
# watchlist_moves (recent step increases for watchlist symbols)
# ---------------------------------------------------------------------------

def replace_watchlist_moves(rows: list[dict]) -> int:
    """Replace all watchlist_moves rows. Called by detect_watchlist_moves pipeline."""
    cols = (
        "symbol", "start_ts", "end_ts", "trough_price", "peak_price",
        "multiplier", "days_to_peak",
    )
    collist = ", ".join(cols)
    placeholders = ", ".join(["%s"] * len(cols))
    payload = [tuple(r.get(c) for c in cols) for r in rows]
    with _conn() as con:
        with con.cursor() as cur:
            cur.execute("DELETE FROM watchlist_moves")
            if payload:
                cur.executemany(
                    f"INSERT INTO watchlist_moves ({collist}) VALUES ({placeholders})",
                    payload,
                )
    return len(payload)


# ---------------------------------------------------------------------------
# catalyst tiers & comprehensive detection
# ---------------------------------------------------------------------------

def load_catalysts_summary() -> list[dict]:
    """Load all detected catalysts with simple yes/no/when/what format.

    Returns catalysts sorted by tier (1-3) and event date (soonest first).
    Output format for user: symbol, detected, event_type, tier, event_date,
    expected_impact, description, confidence, source_url.
    """
    with _cur(row_factory=dict_row) as cur:
        cur.execute("""
            SELECT
                fc.symbol,
                fc.detected,
                fc.event_name AS event_type,
                fc.tier,
                ct.tier_name,
                ct.expected_impact_range AS expected_impact,
                fc.event_date,
                fc.expected_window,
                fc.strategic_summary AS description,
                fc.confidence_score AS confidence,
                fc.source_url,
                a.name,
                a.sector,
                a.industry,
                fc.last_verified_at
            FROM forward_catalysts fc
            LEFT JOIN catalyst_tiers ct ON ct.tier = fc.tier
            JOIN assets a ON a.symbol = fc.symbol
            WHERE fc.detected = TRUE
            ORDER BY fc.tier ASC NULLS LAST, fc.event_date ASC NULLS LAST
        """)
        return [dict(r) for r in cur.fetchall()]


def load_risk_flags() -> list[dict]:
    """Load all active risk flags (reverse splits, delisting risk, etc.)."""
    with _cur(row_factory=dict_row) as cur:
        cur.execute("""
            SELECT
                symbol,
                flag_type,
                flag_date,
                scheduled_date,
                split_ratio,
                description,
                detected_at
            FROM universe_risk_flags
            ORDER BY scheduled_date ASC NULLS LAST, detected_at DESC
        """)
        return [dict(r) for r in cur.fetchall()]


def upsert_catalysts_with_tier(catalysts: list[dict]) -> int:
    """Upsert catalyst results with tier metadata and last_verified_at timestamp.

    Each catalyst dict should have:
    - symbol (required)
    - detected (required)
    - event_name, impact_type, expected_window, strategic_summary, source_url (optional)
    - tier, tier_name, confidence_score, sector_targeted (optional)
    - model (optional, defaults to "sonar-pro")
    """
    if not catalysts:
        return 0

    with _conn() as con:
        with con.cursor() as cur:
            cur.executemany(
                """
                INSERT INTO forward_catalysts
                    (symbol, detected, event_name, impact_type, expected_window,
                     strategic_summary, source_url, model, scanned_at,
                     tier, tier_name, confidence_score, sector_targeted, last_verified_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW(), %s, %s, %s, %s, NOW())
                ON CONFLICT (symbol) DO UPDATE SET
                    detected = EXCLUDED.detected,
                    event_name = EXCLUDED.event_name,
                    impact_type = EXCLUDED.impact_type,
                    expected_window = EXCLUDED.expected_window,
                    strategic_summary = EXCLUDED.strategic_summary,
                    source_url = EXCLUDED.source_url,
                    model = EXCLUDED.model,
                    scanned_at = EXCLUDED.scanned_at,
                    tier = EXCLUDED.tier,
                    tier_name = EXCLUDED.tier_name,
                    confidence_score = EXCLUDED.confidence_score,
                    sector_targeted = EXCLUDED.sector_targeted,
                    last_verified_at = EXCLUDED.last_verified_at
                """,
                [
                    (
                        c["symbol"],
                        c.get("detected", False),
                        c.get("event_name"),
                        c.get("impact_type"),
                        c.get("expected_window"),
                        c.get("strategic_summary"),
                        c.get("source_url"),
                        c.get("model", "sonar-pro"),
                        c.get("tier"),
                        c.get("tier_name"),
                        c.get("confidence_score"),
                        c.get("sector_targeted", False),
                    )
                    for c in catalysts
                ],
            )
    return len(catalysts)


# ---------------------------------------------------------------------------
# company_metrics (NEW - universe-wide quality/financial metrics)
# ---------------------------------------------------------------------------

def upsert_company_metrics(rows: list[dict]) -> int:
    """Insert or update quality/financial metrics for universe stocks.

    Expected keys: symbol, quality_score, net_income, profit_margin, revenue_ttm,
                   insider_score, insider_net_value, roe, debt_to_equity,
                   current_ratio, data_as_of
    """
    if not rows:
        return 0
    with _cur() as cur:
        cur.executemany(
            """
            INSERT INTO company_metrics (
                symbol, quality_score, net_income, profit_margin, revenue_ttm,
                insider_score, insider_net_value, roe, debt_to_equity, current_ratio,
                fetched_at, data_as_of
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW(), %s)
            ON CONFLICT (symbol) DO UPDATE SET
                quality_score = EXCLUDED.quality_score,
                net_income = EXCLUDED.net_income,
                profit_margin = EXCLUDED.profit_margin,
                revenue_ttm = EXCLUDED.revenue_ttm,
                insider_score = EXCLUDED.insider_score,
                insider_net_value = EXCLUDED.insider_net_value,
                roe = EXCLUDED.roe,
                debt_to_equity = EXCLUDED.debt_to_equity,
                current_ratio = EXCLUDED.current_ratio,
                fetched_at = EXCLUDED.fetched_at,
                data_as_of = EXCLUDED.data_as_of
            """,
            [
                (
                    r["symbol"],
                    r.get("quality_score"),
                    r.get("net_income"),
                    r.get("profit_margin"),
                    r.get("revenue_ttm"),
                    r.get("insider_score"),
                    r.get("insider_net_value"),
                    r.get("roe"),
                    r.get("debt_to_equity"),
                    r.get("current_ratio"),
                    r.get("data_as_of"),
                )
                for r in rows
            ],
        )
    return len(rows)


def load_company_metrics() -> list[dict]:
    """Load all company metrics."""
    with _cur(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT symbol, quality_score, net_income, profit_margin, revenue_ttm,
                   insider_score, insider_net_value, roe, debt_to_equity, current_ratio,
                   fetched_at, data_as_of
            FROM company_metrics
            ORDER BY quality_score DESC NULLS LAST
            """
        )
        return cur.fetchall()


# ---------------------------------------------------------------------------
# step_change_history (NEW - all step changes, not just winners)
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
