-- Look-ahead upgrade: screener scores on `watchlist` + a `forward_catalysts`
-- table fed by the Perplexity sonar-pro forward scan.
--
-- Idempotent. Run once in the Supabase SQL editor (or rely on storage.init_db,
-- which mirrors this DDL).

BEGIN;

-- ---------------------------------------------------------------------------
-- watchlist: screener score columns.
-- ---------------------------------------------------------------------------
ALTER TABLE watchlist ADD COLUMN IF NOT EXISTS dollar_volume   DOUBLE PRECISION;
ALTER TABLE watchlist ADD COLUMN IF NOT EXISTS momentum_180d   DOUBLE PRECISION;
ALTER TABLE watchlist ADD COLUMN IF NOT EXISTS momentum_score  DOUBLE PRECISION;
ALTER TABLE watchlist ADD COLUMN IF NOT EXISTS quality_score   DOUBLE PRECISION;
ALTER TABLE watchlist ADD COLUMN IF NOT EXISTS insider_score   DOUBLE PRECISION;
ALTER TABLE watchlist ADD COLUMN IF NOT EXISTS combined_score  DOUBLE PRECISION;
ALTER TABLE watchlist ADD COLUMN IF NOT EXISTS net_income      DOUBLE PRECISION;
ALTER TABLE watchlist ADD COLUMN IF NOT EXISTS profit_margin   DOUBLE PRECISION;
ALTER TABLE watchlist ADD COLUMN IF NOT EXISTS rank            INTEGER;

-- ---------------------------------------------------------------------------
-- forward_catalysts: one latest row per symbol from the sonar-pro scan.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS forward_catalysts (
    symbol             TEXT PRIMARY KEY,
    detected           BOOLEAN,
    event_name         TEXT,
    impact_type        TEXT,
    expected_window    TEXT,
    strategic_summary  TEXT,
    source_url         TEXT,
    model              TEXT,
    scanned_at         TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- FK so PostgREST can embed assets(name) from a forward_catalysts query.
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'forward_catalysts_symbol_fkey') THEN
        ALTER TABLE forward_catalysts ADD CONSTRAINT forward_catalysts_symbol_fkey
            FOREIGN KEY (symbol) REFERENCES assets(symbol) ON DELETE CASCADE;
    END IF;
END $$;

-- RLS: anon read-only (writes happen via the Cloud Run Job's service-role key).
ALTER TABLE forward_catalysts ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS anon_read ON forward_catalysts;
CREATE POLICY anon_read ON forward_catalysts FOR SELECT TO anon USING (true);

COMMIT;
