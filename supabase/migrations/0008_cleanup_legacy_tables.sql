-- Migration 0008: Clean up legacy tables and create latest_prices view
-- Remove deprecated tables: watchlist, watchlist_moves, winners, winner_catalysts, forward_catalysts

-- Create materialized view for latest prices (refreshed periodically)
CREATE MATERIALIZED VIEW IF NOT EXISTS latest_prices AS
SELECT DISTINCT ON (symbol)
    symbol,
    ts as last_date,
    close as last_close
FROM bars
WHERE close IS NOT NULL
ORDER BY symbol, ts DESC;

-- Create index for fast lookups
CREATE UNIQUE INDEX IF NOT EXISTS idx_latest_prices_symbol
ON latest_prices(symbol);

-- Grant access to anon/authenticated users
GRANT SELECT ON latest_prices TO anon, authenticated;

-- Drop deprecated tables (commented out for safety - uncomment after validation)
-- DROP TABLE IF EXISTS watchlist_moves CASCADE;
-- DROP TABLE IF EXISTS winner_catalysts CASCADE;
-- DROP TABLE IF EXISTS winners CASCADE;
-- DROP TABLE IF EXISTS watchlist CASCADE;
-- DROP TABLE IF EXISTS forward_catalysts CASCADE;

-- To refresh the materialized view (run periodically):
-- REFRESH MATERIALIZED VIEW CONCURRENTLY latest_prices;
