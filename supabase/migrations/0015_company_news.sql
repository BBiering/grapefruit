-- Per-company cached AI news profile (fetched from Gemini, stored so repeat
-- clicks don't burn another model call). Anon can read (frontend uses it for
-- the sentiment dot); writes only via the serverless function (service role).
BEGIN;

CREATE TABLE IF NOT EXISTS company_news (
    symbol TEXT PRIMARY KEY REFERENCES assets(symbol) ON DELETE CASCADE,
    content TEXT NOT NULL DEFAULT '',
    sentiment TEXT CHECK (sentiment IN ('positive', 'negative', 'neutral')),
    red_flags TEXT NOT NULL DEFAULT '',
    model TEXT,
    fetched_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE company_news ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS company_news_anon_read ON company_news;
CREATE POLICY company_news_anon_read ON company_news FOR SELECT TO anon USING (true);

GRANT SELECT ON company_news TO anon;
GRANT SELECT, INSERT, UPDATE, DELETE ON company_news TO service_role;

COMMIT;