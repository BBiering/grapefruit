-- Convert forward_catalysts from one current row per symbol into prediction history.
BEGIN;

ALTER TABLE forward_catalysts RENAME TO forward_catalysts_legacy_0012;

CREATE TABLE forward_catalysts (
    id BIGSERIAL PRIMARY KEY,
    symbol TEXT NOT NULL REFERENCES assets(symbol) ON DELETE CASCADE,
    detected BOOLEAN NOT NULL DEFAULT TRUE,
    event_name TEXT NOT NULL,
    impact_type TEXT,
    expected_window TEXT NOT NULL DEFAULT '',
    strategic_summary TEXT,
    source_url TEXT,
    model TEXT,
    confidence TEXT CHECK (confidence IN ('high', 'medium', 'low')),
    expected_impact_pct DOUBLE PRECISION,
    outcome TEXT NOT NULL DEFAULT 'pending'
        CHECK (outcome IN ('pending', 'occurred', 'missed', 'unclear')),
    outcome_notes TEXT,
    reviewed_at TIMESTAMPTZ,
    scanned_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (symbol, event_name, expected_window)
);

-- Preserve detected predictions already fetched. Rows where the old scanner
-- found no catalyst are not events and are intentionally not migrated.
INSERT INTO forward_catalysts (
    symbol, detected, event_name, impact_type, expected_window,
    strategic_summary, source_url, model, confidence, expected_impact_pct,
    scanned_at
)
SELECT
    symbol,
    TRUE,
    COALESCE(NULLIF(event_name, ''), 'Unspecified catalyst'),
    impact_type,
    COALESCE(expected_window, ''),
    strategic_summary,
    source_url,
    model,
    CASE WHEN lower(confidence) IN ('high', 'medium', 'low') THEN lower(confidence) ELSE NULL END,
    expected_impact_pct,
    scanned_at
FROM forward_catalysts_legacy_0012
WHERE detected = TRUE;

DROP TABLE forward_catalysts_legacy_0012 CASCADE;

CREATE INDEX idx_forward_catalysts_symbol ON forward_catalysts(symbol);
CREATE INDEX idx_forward_catalysts_event_date ON forward_catalysts(expected_window);
CREATE INDEX idx_forward_catalysts_confidence ON forward_catalysts(confidence);
CREATE INDEX idx_forward_catalysts_outcome ON forward_catalysts(outcome);

ALTER TABLE forward_catalysts ENABLE ROW LEVEL SECURITY;
CREATE POLICY anon_read ON forward_catalysts FOR SELECT TO anon USING (true);
GRANT SELECT ON forward_catalysts TO anon, authenticated;

COMMIT;
