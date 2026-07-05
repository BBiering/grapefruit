-- Add strategy_tag column to watchlist for layered funnel system

ALTER TABLE watchlist ADD COLUMN IF NOT EXISTS strategy_tag TEXT;

-- Add check constraint to enforce valid tags (idempotent)
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conname = 'watchlist_strategy_tag_check'
  ) THEN
    ALTER TABLE watchlist ADD CONSTRAINT watchlist_strategy_tag_check
      CHECK (strategy_tag IN ('Buy Manually', 'Watchlist', 'Pass'));
  END IF;
END $$;

-- Index for filtering by tag
CREATE INDEX IF NOT EXISTS watchlist_strategy_tag_idx ON watchlist(strategy_tag);

COMMENT ON COLUMN watchlist.strategy_tag IS
  'Strategy alignment: "Buy Manually" (Quality+Catalyst), "Watchlist" (Quality only), "Pass" (no quality alignment)';
