-- Grapefruit redesign migration.
-- Drops the dead "hits / catalysts / news_cache" tables and creates the new
-- "winners / winner_catalysts / watchlist / upcoming_events / pipeline_runs"
-- tables. Keeps bars, assets, app_state untouched.
--
-- Run once in the Supabase SQL editor against an empty / acceptable-to-wipe
-- project. Idempotent: every CREATE uses IF NOT EXISTS, every DROP uses IF
-- EXISTS, and CREATE POLICY blocks check for existence first.

BEGIN;

-- ---------------------------------------------------------------------------
-- Drop the legacy tables that the new architecture replaces.
-- ---------------------------------------------------------------------------
DROP TABLE IF EXISTS hits        CASCADE;
DROP TABLE IF EXISTS catalysts   CASCADE;
DROP TABLE IF EXISTS news_cache  CASCADE;

-- ---------------------------------------------------------------------------
-- New: winners — one row per detected steep-rise event.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS winners (
    id                       BIGSERIAL PRIMARY KEY,
    symbol                   TEXT NOT NULL,
    start_ts                 DATE NOT NULL,
    end_ts                   DATE NOT NULL,
    days_to_peak             INTEGER NOT NULL,
    trough_price             DOUBLE PRECISION NOT NULL,
    peak_price               DOUBLE PRECISION NOT NULL,
    multiplier               DOUBLE PRECISION NOT NULL,
    post_peak_retention      DOUBLE PRECISION,
    breakout_ratio           DOUBLE PRECISION,
    market_cap_usd_at_peak   DOUBLE PRECISION,
    sector                   TEXT,
    industry                 TEXT,
    status                   TEXT NOT NULL CHECK (status IN ('held', 'faded')),
    detected_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (symbol, end_ts)
);
CREATE INDEX IF NOT EXISTS winners_symbol_idx     ON winners(symbol);
CREATE INDEX IF NOT EXISTS winners_detected_idx   ON winners(detected_at DESC);
CREATE INDEX IF NOT EXISTS winners_status_idx     ON winners(status);

-- ---------------------------------------------------------------------------
-- New: winner_catalysts — one row per (winner, perplexity lookup).
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS winner_catalysts (
    winner_id              BIGINT PRIMARY KEY REFERENCES winners(id) ON DELETE CASCADE,
    headline               TEXT,
    summary                TEXT,
    spike_explanation      TEXT,
    was_foreseeable        BOOLEAN,
    foreseeable_evidence   TEXT,
    perplexity_citations   JSONB,
    fetched_at             TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ---------------------------------------------------------------------------
-- New: watchlist — Part 2 candidate set (refreshed weekly).
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS watchlist (
    symbol           TEXT PRIMARY KEY,
    last_close       DOUBLE PRECISION,
    market_cap_usd   DOUBLE PRECISION,
    sector           TEXT,
    industry         TEXT,
    why_listed       TEXT NOT NULL,
    added_at         TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ---------------------------------------------------------------------------
-- New: upcoming_events — Part 2 forward-looking catalysts.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS upcoming_events (
    id            BIGSERIAL PRIMARY KEY,
    symbol        TEXT NOT NULL,
    event_ts      DATE NOT NULL,
    event_type    TEXT NOT NULL CHECK (event_type IN ('earnings', 'trial_phase3', 'other')),
    title         TEXT,
    source        TEXT,
    source_url    TEXT,
    est_revenue   DOUBLE PRECISION,
    est_eps       DOUBLE PRECISION,
    fetched_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (symbol, event_ts, event_type, title)
);
CREATE INDEX IF NOT EXISTS upcoming_events_symbol_idx  ON upcoming_events(symbol);
CREATE INDEX IF NOT EXISTS upcoming_events_ts_idx      ON upcoming_events(event_ts);

-- ---------------------------------------------------------------------------
-- New: pipeline_runs — observability for each scheduled job.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS pipeline_runs (
    id              BIGSERIAL PRIMARY KEY,
    job_name        TEXT NOT NULL,
    started_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at     TIMESTAMPTZ,
    status          TEXT NOT NULL CHECK (status IN ('running', 'done', 'error')),
    rows_processed  INTEGER,
    error_msg       TEXT
);
CREATE INDEX IF NOT EXISTS pipeline_runs_job_idx ON pipeline_runs(job_name, started_at DESC);

-- ---------------------------------------------------------------------------
-- Row Level Security: enable on every table; grant the anon role SELECT only.
-- Writes happen via the service-role key (from the Cloud Run Job), which
-- bypasses RLS.
-- ---------------------------------------------------------------------------
ALTER TABLE bars             ENABLE ROW LEVEL SECURITY;
ALTER TABLE assets           ENABLE ROW LEVEL SECURITY;
ALTER TABLE app_state        ENABLE ROW LEVEL SECURITY;
ALTER TABLE winners          ENABLE ROW LEVEL SECURITY;
ALTER TABLE winner_catalysts ENABLE ROW LEVEL SECURITY;
ALTER TABLE watchlist        ENABLE ROW LEVEL SECURITY;
ALTER TABLE upcoming_events  ENABLE ROW LEVEL SECURITY;
ALTER TABLE pipeline_runs    ENABLE ROW LEVEL SECURITY;

DO $$
DECLARE
    t TEXT;
BEGIN
    FOREACH t IN ARRAY ARRAY[
        'bars', 'assets', 'app_state',
        'winners', 'winner_catalysts', 'watchlist',
        'upcoming_events', 'pipeline_runs'
    ]
    LOOP
        EXECUTE format(
            'DROP POLICY IF EXISTS anon_read ON %I;
             CREATE POLICY anon_read ON %I FOR SELECT TO anon USING (true);',
            t, t
        );
    END LOOP;
END $$;

COMMIT;
