-- Grapefruit consolidation: one canonical schema for the seven active tables.
BEGIN;

-- The migration history renamed forward_catalysts to predicted_catalysts in
-- 0007, while older backend init code could recreate forward_catalysts. Keep
-- one canonical name for the current code: forward_catalysts.
DO $$
BEGIN
    IF to_regclass('public.forward_catalysts') IS NULL
       AND to_regclass('public.predicted_catalysts') IS NOT NULL THEN
        ALTER TABLE predicted_catalysts RENAME TO forward_catalysts;
    ELSIF to_regclass('public.forward_catalysts') IS NOT NULL
          AND to_regclass('public.predicted_catalysts') IS NOT NULL THEN
        DROP TABLE predicted_catalysts CASCADE;
    END IF;
END $$;

-- Remove legacy data stores and their dependent objects.
DROP TABLE IF EXISTS winners CASCADE;
DROP TABLE IF EXISTS winner_catalysts CASCADE;
DROP TABLE IF EXISTS watchlist CASCADE;
DROP TABLE IF EXISTS watchlist_moves CASCADE;
DROP TABLE IF EXISTS company_metrics CASCADE;
DROP TABLE IF EXISTS upcoming_events CASCADE;
DROP TABLE IF EXISTS catalyst_tiers CASCADE;
DROP TABLE IF EXISTS universe_risk_flags CASCADE;

-- Ensure the canonical future-catalyst table exists and has the new fields.
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
);
ALTER TABLE forward_catalysts ADD COLUMN IF NOT EXISTS confidence TEXT;
ALTER TABLE forward_catalysts ADD COLUMN IF NOT EXISTS expected_impact_pct DOUBLE PRECISION;

-- Only major events remain: 5x+ within two weeks.
DELETE FROM step_change_history WHERE tier IS DISTINCT FROM 'major';
ALTER TABLE step_change_history DROP CONSTRAINT IF EXISTS step_change_history_tier_check;
ALTER TABLE step_change_history
    ADD CONSTRAINT step_change_history_tier_check CHECK (tier = 'major');

CREATE INDEX IF NOT EXISTS idx_forward_catalysts_confidence
    ON forward_catalysts(confidence);

COMMIT;
