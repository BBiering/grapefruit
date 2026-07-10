-- Migration 0009: Drop legacy tables now that new schema is live
-- Tables to remove: watchlist, watchlist_moves, winners, winner_catalysts
-- Note: forward_catalysts was already renamed to predicted_catalysts in 0007

-- Drop legacy watchlist tables
DROP TABLE IF EXISTS watchlist_moves CASCADE;
DROP TABLE IF EXISTS watchlist CASCADE;

-- Drop legacy winner tables
DROP TABLE IF EXISTS winner_catalysts CASCADE;
DROP TABLE IF EXISTS winners CASCADE;

-- Drop legacy upcoming_events (now covered by predicted_catalysts tier 2)
DROP TABLE IF EXISTS upcoming_events CASCADE;

-- Verify replacement tables exist
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_tables WHERE tablename = 'company_metrics') THEN
        RAISE EXCEPTION 'company_metrics table does not exist - run migration 0007 first';
    END IF;

    IF NOT EXISTS (SELECT 1 FROM pg_tables WHERE tablename = 'step_change_history') THEN
        RAISE EXCEPTION 'step_change_history table does not exist - run migration 0007 first';
    END IF;

    IF NOT EXISTS (SELECT 1 FROM pg_tables WHERE tablename = 'predicted_catalysts') THEN
        RAISE EXCEPTION 'predicted_catalysts table does not exist - run migration 0007 first';
    END IF;
END $$;
