-- Add foreign keys from winners.symbol and watchlist.symbol to assets.symbol.
--
-- PostgREST (the Supabase REST API) only allows embedding a related table
-- (e.g. winners.select("..., assets(name)")) when a real foreign key links
-- them. Without these FKs the frontend fails with:
--   "Could not find a relationship between 'winners' and 'assets'
--    in the schema cache".
--
-- assets.symbol is the PRIMARY KEY, so it's a valid FK target. The pipeline
-- always upserts assets before deriving winners/watchlist, so no orphan rows
-- are expected; the FKs are added NOT VALID first, then validated, so the
-- migration surfaces (rather than silently tolerates) any pre-existing orphans.

BEGIN;

-- winners.symbol -> assets.symbol
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'winners_symbol_fkey'
    ) THEN
        ALTER TABLE winners
            ADD CONSTRAINT winners_symbol_fkey
            FOREIGN KEY (symbol) REFERENCES assets(symbol)
            ON DELETE CASCADE NOT VALID;
        ALTER TABLE winners VALIDATE CONSTRAINT winners_symbol_fkey;
    END IF;
END $$;

-- watchlist.symbol -> assets.symbol
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'watchlist_symbol_fkey'
    ) THEN
        ALTER TABLE watchlist
            ADD CONSTRAINT watchlist_symbol_fkey
            FOREIGN KEY (symbol) REFERENCES assets(symbol)
            ON DELETE CASCADE NOT VALID;
        ALTER TABLE watchlist VALIDATE CONSTRAINT watchlist_symbol_fkey;
    END IF;
END $$;

-- Make PostgREST pick up the new relationships immediately.
NOTIFY pgrst, 'reload schema';

COMMIT;
