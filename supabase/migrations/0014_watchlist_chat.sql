-- User watchlist + per-company chat history (public tool, anon read/write).
BEGIN;

CREATE TABLE IF NOT EXISTS watchlist (
    symbol TEXT PRIMARY KEY REFERENCES assets(symbol) ON DELETE CASCADE,
    added_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
ALTER TABLE watchlist ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS watchlist_anon_read ON watchlist;
CREATE POLICY watchlist_anon_read ON watchlist FOR SELECT TO anon USING (true);
DROP POLICY IF EXISTS watchlist_anon_insert ON watchlist;
CREATE POLICY watchlist_anon_insert ON watchlist FOR INSERT TO anon WITH CHECK (true);
DROP POLICY IF EXISTS watchlist_anon_delete ON watchlist;
CREATE POLICY watchlist_anon_delete ON watchlist FOR DELETE TO anon USING (true);
GRANT SELECT, INSERT, DELETE ON watchlist TO anon, authenticated;

CREATE TABLE IF NOT EXISTS chat_messages (
    id BIGSERIAL PRIMARY KEY,
    symbol TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
    content TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS chat_messages_symbol_idx ON chat_messages(symbol, created_at);
ALTER TABLE chat_messages ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS chat_anon_read ON chat_messages;
CREATE POLICY chat_anon_read ON chat_messages FOR SELECT TO anon USING (true);
DROP POLICY IF EXISTS chat_anon_insert ON chat_messages;
CREATE POLICY chat_anon_insert ON chat_messages FOR INSERT TO anon WITH CHECK (true);
DROP POLICY IF EXISTS chat_anon_delete ON chat_messages;
CREATE POLICY chat_anon_delete ON chat_messages FOR DELETE TO anon USING (true);
GRANT SELECT, INSERT, DELETE ON chat_messages TO anon, authenticated;

COMMIT;