-- Add watchlist_moves table to store recent step increases for watchlist symbols
-- (used to highlight the move that drove momentum selection)

CREATE TABLE IF NOT EXISTS watchlist_moves (
    symbol TEXT PRIMARY KEY REFERENCES assets(symbol) ON DELETE CASCADE,
    start_ts DATE NOT NULL,
    end_ts DATE NOT NULL,
    trough_price FLOAT NOT NULL,
    peak_price FLOAT NOT NULL,
    multiplier FLOAT NOT NULL,
    days_to_peak INT NOT NULL,
    detected_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- RLS: public read
ALTER TABLE watchlist_moves ENABLE ROW LEVEL SECURITY;
CREATE POLICY "watchlist_moves: public read" ON watchlist_moves FOR SELECT USING (true);

-- Index for FK lookups
CREATE INDEX IF NOT EXISTS watchlist_moves_symbol_idx ON watchlist_moves(symbol);

COMMENT ON TABLE watchlist_moves IS 'Recent step increases for watchlist symbols (past 180 days), used to visualize the momentum that drove selection';
