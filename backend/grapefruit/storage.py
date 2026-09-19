"""Postgres-backed storage layer (Supabase). Public API matches the prior
DuckDB-backed module so the rest of the codebase doesn't need changes.

DDL is idempotent in init_db(); no migration tooling.
"""
from __future__ import annotations

import json
import re
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


def close_pool(timeout: float = 5.0) -> None:
    """Close the process-wide PostgreSQL pool and its worker threads."""
    global _pool
    with _pool_lock:
        pool, _pool = _pool, None
    if pool is not None:
        pool.close(timeout=timeout)


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
                refreshed_at TIMESTAMPTZ,
                sector_attempted_at TIMESTAMPTZ
            )
            """
        )
        cur.execute("ALTER TABLE assets ADD COLUMN IF NOT EXISTS sector_attempted_at TIMESTAMPTZ")
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
                id BIGSERIAL PRIMARY KEY,
                symbol TEXT NOT NULL REFERENCES assets(symbol) ON DELETE CASCADE,
                detected BOOLEAN NOT NULL DEFAULT TRUE,
                event_name TEXT NOT NULL,
                impact_type TEXT,
                expected_window TEXT NOT NULL DEFAULT '',
                strategic_summary TEXT,
                source_url TEXT,
                model TEXT,
                confidence TEXT CHECK (confidence IN ('high', 'medium', 'low')),
                expected_impact_pct DOUBLE PRECISION,
                actual_impact_pct DOUBLE PRECISION,
                outcome TEXT NOT NULL DEFAULT 'pending'
                    CHECK (outcome IN ('pending', 'occurred', 'missed', 'unclear')),
                outcome_notes TEXT,
                reviewed_at TIMESTAMPTZ,
                scanned_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                UNIQUE (symbol, event_name, expected_window)
            )
            """
        )
        cur.execute("ALTER TABLE forward_catalysts ADD COLUMN IF NOT EXISTS actual_impact_pct DOUBLE PRECISION")
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
                tier TEXT CHECK (tier IN ('major')),
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

        # User watchlist (distinct from the legacy screener `watchlist` dropped
        # above). Public tool, no auth: anon can read/write it via Supabase.
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS excluded_symbols (
                symbol TEXT PRIMARY KEY,
                pruned_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );

            CREATE TABLE IF NOT EXISTS watchlist (
                symbol TEXT PRIMARY KEY REFERENCES assets(symbol) ON DELETE CASCADE,
                added_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """
        )
        cur.execute("ALTER TABLE watchlist ENABLE ROW LEVEL SECURITY")
        cur.execute("DROP POLICY IF EXISTS watchlist_anon_read ON watchlist")
        cur.execute("CREATE POLICY watchlist_anon_read ON watchlist FOR SELECT TO anon USING (true)")
        cur.execute("DROP POLICY IF EXISTS watchlist_anon_insert ON watchlist")
        cur.execute("CREATE POLICY watchlist_anon_insert ON watchlist FOR INSERT TO anon WITH CHECK (true)")
        cur.execute("DROP POLICY IF EXISTS watchlist_anon_delete ON watchlist")
        cur.execute("CREATE POLICY watchlist_anon_delete ON watchlist FOR DELETE TO anon USING (true)")
        cur.execute("GRANT SELECT, INSERT, DELETE ON watchlist TO anon, authenticated")

        # Per-company chat history (Perplexity Q&A). Public, anon read/write.
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS chat_messages (
                id BIGSERIAL PRIMARY KEY,
                symbol TEXT NOT NULL,
                role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
                content TEXT NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """
        )
        cur.execute("CREATE INDEX IF NOT EXISTS chat_messages_symbol_idx ON chat_messages(symbol, created_at)")
        cur.execute("ALTER TABLE chat_messages ENABLE ROW LEVEL SECURITY")
        cur.execute("DROP POLICY IF EXISTS chat_anon_read ON chat_messages")
        cur.execute("CREATE POLICY chat_anon_read ON chat_messages FOR SELECT TO anon USING (true)")
        cur.execute("DROP POLICY IF EXISTS chat_anon_insert ON chat_messages")
        cur.execute("CREATE POLICY chat_anon_insert ON chat_messages FOR INSERT TO anon WITH CHECK (true)")
        cur.execute("DROP POLICY IF EXISTS chat_anon_delete ON chat_messages")
        cur.execute("CREATE POLICY chat_anon_delete ON chat_messages FOR DELETE TO anon USING (true)")
        cur.execute("GRANT SELECT, INSERT, DELETE ON chat_messages TO anon, authenticated")


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


def bar_count(symbol: str) -> int:
    with _cur() as cur:
        cur.execute("SELECT COUNT(*) FROM bars WHERE symbol = %s", [symbol])
        return int(cur.fetchone()[0])


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
                -- refresh_universe always sends NULL here; keep a known
                -- classification instead of wiping it each week.
                sector = COALESCE(EXCLUDED.sector, assets.sector),
                industry = COALESCE(EXCLUDED.industry, assets.industry),
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
                -- preserve a known classification when incoming sector/industry
                -- are NULL (refresh_universe always builds rows with None).
                sector = COALESCE(EXCLUDED.sector, assets.sector),
                industry = COALESCE(EXCLUDED.industry, assets.industry),
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
    """Symbols still unclassified by industry, oldest-attempt first.

    Keyed on `industry` (not sector) and ordered so never-tried names
    (NULL sector_attempted_at) are processed before already-failed ones.
    Used by refresh_sectors to backfill sector/industry for the universe."""
    with _cur() as cur:
        cur.execute(
            """
            SELECT a.symbol
            FROM assets a
            WHERE (a.industry IS NULL OR a.industry = '')
            ORDER BY a.sector_attempted_at ASC NULLS FIRST, a.symbol
            LIMIT %s
            """,
            [limit],
        )
        return [r[0] for r in cur.fetchall()]


def mark_sector_attempted(symbol: str) -> None:
    """Record that refresh_sectors tried (successfully or not) to classify this
    symbol. Lets a later cleanup distinguish 'never tried yet' from
    'tried and EODHD had no data', so unresolved-but-legit names get retried
    before being purged."""
    with _cur() as cur:
        cur.execute(
            "UPDATE assets SET sector_attempted_at = NOW() WHERE symbol = %s",
            [symbol],
        )


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


_STOP_TOKENS = {
    "results", "topline", "headline", "top", "line", "data", "readout", "interim",
    "final", "study", "trial", "the", "of", "in", "for", "and", "a", "an", "to",
    "from", "phase", "pivotal", "planned", "upcoming", "expected", "catalyst",
    "event", "announcement", "company", "stock",
}


def _norm_tokens(name: str) -> list[str]:
    import re
    return [
        t for t in re.sub(r"[^a-z0-9]+", " ", name.lower()).split()
        if len(t) > 2 and t not in _STOP_TOKENS
    ]


def _similarity(a_toks: list[str], b_toks: list[str]) -> float:
    if not a_toks or not b_toks:
        return 0.0
    sb = set(b_toks)
    inter = sum(1 for t in a_toks if t in sb)
    return inter / min(len(a_toks), len(b_toks))


def _distinctive_shared(a_toks: list[str], b_toks: list[str]) -> bool:
    sb = set(b_toks)
    return any(len(t) >= 6 and t in sb for t in a_toks)


def _matches_existing(incoming: dict, existing: dict) -> bool:
    """Near-duplicate? Same event reworded by the LLM across scans, or the
    same window+type. Mirrors the frontend dedupe so display stays 1:1."""
    if incoming["symbol"] != existing["symbol"]:
        return False
    inc_name = (incoming.get("event_name") or "").strip()
    ex_name = (existing.get("event_name") or "").strip()
    inc_win = incoming.get("expected_window") or ""
    ex_win = existing.get("expected_window") or ""
    if inc_win and ex_win and inc_win == ex_win and incoming.get("impact_type") == existing.get("impact_type"):
        return True
    if not inc_name or not ex_name:
        return False
    it, et = _norm_tokens(inc_name), _norm_tokens(ex_name)
    same_type = incoming.get("impact_type") == existing.get("impact_type")
    return _similarity(it, et) >= 0.55 or (same_type and _distinctive_shared(it, et))


# ---------------------------------------------------------------------------
# Free-text date extraction for catalyst windows ("30 Sept 2026", "Q4 2026",
# "H1 2027", "September 2026") -> canonical "YYYY-MM-DD" / "Qx YYYY" / "Hx YYYY".
# ---------------------------------------------------------------------------
_MONTH_NAMES = (
    r"jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|"
    r"aug(?:ust)?|sept(?:ember)?|sep|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?"
)
_WINDOW_ISO = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
_WINDOW_MONTH = re.compile(
    r"(?i)\b(?:(\d{1,2})(?:st|nd|rd|th)?[\s,.]*)?(" + _MONTH_NAMES + r")(?:[\s,.]*(\d{4}))?(?!-?\d)\b"
)
_WINDOW_QUARTER = re.compile(r"(?i)\bq([1-4])\s*['’]?\s*(\d{2}|\d{4})\b")
_WINDOW_HALF = re.compile(r"(?i)\bh([12])\s*['’]?\s*(\d{2}|\d{4})\b")
_MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "sept": 9, "oct": 10, "nov": 11, "dec": 12,
}

# Major recurring congresses -> their usual month, so a bare "ESMO 2026"-style
# name still yields an approximate quarter.
_CONFERENCE_MONTHS = {
    "esmo": 9, "easd": 9, "asbrm": 9, "asco": 6, "aacr": 4, "jpm": 1,
}


def _year4(y: str) -> str:
    return y if len(y) == 4 else f"{2000 + int(y)}"


def extract_window_from_text(text: str | None, today: date | None = None) -> str:
    """Best-effort catalyst window from free text (event names). Returns a
    canonical value the rest of the stack understands, or '' when absent.

    Handles: ISO dates, "30 Sept 2026" / "September 2026", month without a
    year ("September data cut" -> nearest occurrence in the scan window),
    "Q4 2026"/"H1 2027" (also 2-digit years), and conference-year names
    ("ESMO 2026" -> its usual quarter).
    """
    if not text:
        return ""
    today = today or date.today()
    s = text.strip()
    m = _WINDOW_ISO.search(s)
    if m:
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if 1 <= mo <= 12 and 1 <= d <= 31:
            return f"{y:04d}-{mo:02d}-{d:02d}"
    m = _WINDOW_MONTH.search(s)
    if m:
        mo = _MONTHS[m.group(2).lower()[:3]]
        day = int(m.group(1)) if m.group(1) else None
        yy = m.group(3)
        if not yy:
            # Month without a year: this month if we're in it, else the
            # nearest month-start at/after today.
            for y in (today.year, today.year + 1):
                if day:
                    try:
                        cand = date(y, mo, day)
                    except ValueError:
                        continue
                    if today <= cand:
                        return cand.isoformat()
                else:
                    if mo == today.month and y == today.year:
                        return f"Q{(mo - 1) // 3 + 1} {y}"
                    if today < date(y, mo, 1):
                        return f"Q{(mo - 1) // 3 + 1} {y}"
            return ""
        if day and 1 <= day <= 31:
            return f"{int(_year4(yy)):04d}-{mo:02d}-{day:02d}"
        return f"Q{(mo - 1) // 3 + 1} {_year4(yy)}"
    m = _WINDOW_QUARTER.search(s)
    if m:
        return f"Q{m.group(1)} {_year4(m.group(2))}"
    m = _WINDOW_HALF.search(s)
    if m:
        return f"H{m.group(1)} {_year4(m.group(2))}"
    # Conference-year name ("ESMO 2026", "ERS Congress 2026"...) -> usual quarter.
    low = s.lower()
    for conf, mo in _CONFERENCE_MONTHS.items():
        if conf in low:
            ym = re.search(r"\b(20\d{2})\b", s)
            if ym:
                return f"Q{(mo - 1) // 3 + 1} {ym.group(1)}"
    return ""


def replace_forward_catalysts(rows: list[dict]) -> int:
    """Upsert detected predictions without deleting prior prediction history.

    The UNIQUE (symbol, event_name, expected_window) key does not catch the
    LLM's weekly rewordings of the same event, so without this guard each scan
    appends near-duplicate rows. Incoming rows that match an existing row for
    the same symbol (name similarity / same window+type) refresh that row
    instead of inserting a new one.
    """
    detected_rows = [r for r in rows if r.get("detected")]
    if not detected_rows:
        return 0

    # The scan prompt often leaves expected_window empty while the event name
    # carries the date ("30 Sept 2026", "Q4 2026"...). Fill it at write time so
    # the header horizon and chart placement always benefit.
    for row in detected_rows:
        if not (row.get("expected_window") or "").strip():
            parsed = extract_window_from_text(row.get("event_name") or "")
            if parsed:
                row["expected_window"] = parsed

    symbols = [r["symbol"] for r in detected_rows]
    with _conn() as con:
        with con.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "SELECT id, symbol, event_name, impact_type, expected_window "
                "FROM forward_catalysts WHERE symbol = ANY(%s)",
                [symbols],
            )
            existing_all = cur.fetchall()

    by_symbol: dict[str, list[dict]] = {}
    for ex in existing_all:
        by_symbol.setdefault(ex["symbol"], []).append(ex)

    updates: list[tuple[dict, dict]] = []  # (existing row, incoming row)
    inserts: list[dict] = []
    for row in detected_rows:
        matched = next(
            (ex for ex in by_symbol.get(row["symbol"], []) if _matches_existing(row, ex)),
            None,
        )
        if matched:
            updates.append((matched, row))
        else:
            inserts.append(row)

    with _conn() as con:
        with con.cursor() as cur:
            if inserts:
                cur.executemany(
                    """
                    INSERT INTO forward_catalysts (
                        symbol, detected, event_name, impact_type, expected_window,
                        strategic_summary, source_url, model, confidence,
                        expected_impact_pct, scanned_at
                    )
                    VALUES (%s, TRUE, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
                    ON CONFLICT (symbol, event_name, expected_window) DO UPDATE SET
                        detected = TRUE,
                        impact_type = EXCLUDED.impact_type,
                        strategic_summary = EXCLUDED.strategic_summary,
                        source_url = EXCLUDED.source_url,
                        model = EXCLUDED.model,
                        confidence = EXCLUDED.confidence,
                        expected_impact_pct = EXCLUDED.expected_impact_pct,
                        scanned_at = EXCLUDED.scanned_at
                    """,
                    [
                        (
                            r["symbol"],
                            r.get("event_name") or "Unspecified catalyst",
                            r.get("impact_type"),
                            r.get("expected_window") or "",
                            r.get("strategic_summary"),
                            r.get("source_url"),
                            r.get("model", "agent-fast"),
                            r.get("confidence"),
                            r.get("expected_impact_pct"),
                        )
                        for r in inserts
                    ],
                )
            if updates:
                cur.executemany(
                    """
                    UPDATE forward_catalysts SET
                        detected = TRUE,
                        impact_type = %s,
                        strategic_summary = %s,
                        source_url = %s,
                        model = %s,
                        confidence = %s,
                        expected_impact_pct = %s,
                        scanned_at = NOW()
                    WHERE id = %s
                    """,
                    [
                        (
                            row.get("impact_type"),
                            row.get("strategic_summary"),
                            row.get("source_url"),
                            row.get("model", "agent-fast"),
                            row.get("confidence"),
                            row.get("expected_impact_pct"),
                            existing["id"],
                        )
                        for existing, row in updates
                    ],
                )
    return len(detected_rows)


def load_pending_predictions(limit: int = 1000) -> list[dict]:
    """Load predictions eligible for outcome review."""
    with _cur(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT id, symbol, expected_window, expected_impact_pct, confidence
            FROM forward_catalysts
            WHERE detected = TRUE AND outcome = 'pending'
              AND expected_window ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}$'
              AND expected_window::date < CURRENT_DATE
            ORDER BY expected_window ASC
            LIMIT %s
            """,
            [limit],
        )
        return [dict(row) for row in cur.fetchall()]


def update_prediction_outcome(
    prediction_id: int,
    *,
    outcome: str,
    actual_impact_pct: float | None,
    notes: str,
) -> None:
    with _cur() as cur:
        cur.execute(
            """
            UPDATE forward_catalysts
            SET outcome = %s,
                actual_impact_pct = %s,
                outcome_notes = %s,
                reviewed_at = NOW()
            WHERE id = %s AND outcome = 'pending'
            """,
            [outcome, actual_impact_pct, notes, prediction_id],
        )


def load_prediction_performance() -> list[dict]:
    with _cur(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT outcome, confidence, expected_impact_pct, actual_impact_pct
            FROM forward_catalysts
            WHERE detected = TRUE
            """
        )
        return [dict(row) for row in cur.fetchall()]


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


def symbols_biotech() -> list[str]:
    """Symbols explicitly classified as Biotechnology.

    The universe table can temporarily hold NULL-industry rows (grace window
    before sector backfill resolves them). Price/bar/catalyst consumers must
    only touch confirmed biotech names, or they burn API/credits on banks and
    miners that just haven't been classified yet."""
    with _cur() as cur:
        cur.execute(
            "SELECT symbol FROM assets WHERE industry = 'Biotechnology' ORDER BY symbol"
        )
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
                row.get("model", "agent-low"),
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


def delete_asset(symbol: str) -> None:
    """Delete one asset and its bars. FK cascades remove step changes,
    step-change catalysts, and forward catalysts for it."""
    with _conn() as con:
        with con.cursor() as cur:
            cur.execute("DELETE FROM bars WHERE symbol = %s", [symbol])
            cur.execute("DELETE FROM assets WHERE symbol = %s", [symbol])


def prune_assets_below_min_cap(min_cap_usd: float) -> dict[str, int]:
    """Delete assets (and their bars, no FK) whose stored market cap is below
    the universe floor. Call AFTER upsert_assets: symbols still below the floor
    after this run's fresh values are evaluated get removed; one that recovered
    above the floor was just re-upserted and is kept. Returns counts of
    deleted rows per table."""
    with _conn() as con:
        with con.cursor() as cur:
            cur.execute(
                """
                DELETE FROM bars
                WHERE symbol IN (
                    SELECT symbol FROM assets
                    WHERE market_cap_usd IS NOT NULL AND market_cap_usd < %s
                )
                """,
                [min_cap_usd],
            )
            bars_deleted = cur.rowcount
            cur.execute(
                """
                DELETE FROM assets
                WHERE market_cap_usd IS NOT NULL AND market_cap_usd < %s
                """,
                [min_cap_usd],
            )
            assets_deleted = cur.rowcount
    return {"assets": assets_deleted, "bars": bars_deleted}


def exclude_symbol(symbol: str) -> None:
    """Tombstone a symbol classified as non-biotech so refresh_universe does
    not re-admit it from the bulk feeds on the next run."""
    with _cur() as cur:
        cur.execute(
            "INSERT INTO excluded_symbols (symbol) VALUES (%s) ON CONFLICT DO NOTHING",
            [symbol],
        )


def excluded_symbols() -> set[str]:
    with _cur() as cur:
        cur.execute("SELECT symbol FROM excluded_symbols")
        return {r[0] for r in cur.fetchall()}


def sector_tried_once(symbol: str) -> bool:
    """True if refresh_sectors has attempted this symbol before. A second
    attempt that still yields no industry is tombstoned as unclassifiable
    junk instead of being retried forever."""
    with _cur() as cur:
        cur.execute("SELECT sector_attempted_at IS NOT NULL FROM assets WHERE symbol = %s", [symbol])
        row = cur.fetchone()
        return bool(row and row[0])
