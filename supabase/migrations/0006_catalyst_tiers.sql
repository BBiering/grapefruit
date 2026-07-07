-- Comprehensive Catalyst Detection System Schema
-- Adds tier classification, confidence scores, and risk flags

-- 1. Extend forward_catalysts table with tier metadata
ALTER TABLE forward_catalysts ADD COLUMN IF NOT EXISTS tier INTEGER;
ALTER TABLE forward_catalysts ADD COLUMN IF NOT EXISTS tier_name TEXT;
ALTER TABLE forward_catalysts ADD COLUMN IF NOT EXISTS event_date DATE;
ALTER TABLE forward_catalysts ADD COLUMN IF NOT EXISTS confidence_score REAL;
ALTER TABLE forward_catalysts ADD COLUMN IF NOT EXISTS sector_targeted BOOLEAN DEFAULT false;
ALTER TABLE forward_catalysts ADD COLUMN IF NOT EXISTS last_verified_at TIMESTAMPTZ;

-- Indexes for efficient querying
CREATE INDEX IF NOT EXISTS idx_forward_catalysts_tier ON forward_catalysts(tier);
CREATE INDEX IF NOT EXISTS idx_forward_catalysts_event_date ON forward_catalysts(event_date);
CREATE INDEX IF NOT EXISTS idx_forward_catalysts_last_verified ON forward_catalysts(last_verified_at);

-- 2. Create catalyst_tiers reference table
CREATE TABLE IF NOT EXISTS catalyst_tiers (
    tier INTEGER PRIMARY KEY,
    tier_name TEXT NOT NULL,
    expected_impact_range TEXT NOT NULL,
    description TEXT
);

-- Populate tier definitions
INSERT INTO catalyst_tiers (tier, tier_name, expected_impact_range, description) VALUES
    (1, 'Systemic Volatility', '+100% to +500%', 'Binary events that alter structural valuation overnight'),
    (2, 'Corporate Acceleration', '+20% to +50%', 'Business model acceleration events'),
    (3, 'Structural Maintenance', 'Highly Volatile', 'Technical events affecting share structure, not organic value')
ON CONFLICT (tier) DO NOTHING;

-- 3. Create universe_risk_flags table for programmatic exclusions
CREATE TABLE IF NOT EXISTS universe_risk_flags (
    symbol TEXT PRIMARY KEY,
    flag_type TEXT NOT NULL CHECK (flag_type IN ('reverse_split', 'delisting_risk', 'fraud_investigation', 'bankruptcy')),
    flag_date DATE NOT NULL,
    scheduled_date DATE,
    split_ratio TEXT,
    description TEXT,
    detected_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    FOREIGN KEY (symbol) REFERENCES assets(symbol) ON DELETE CASCADE
);

-- Indexes for risk flag queries
CREATE INDEX IF NOT EXISTS idx_risk_flags_type ON universe_risk_flags(flag_type);
CREATE INDEX IF NOT EXISTS idx_risk_flags_scheduled ON universe_risk_flags(scheduled_date);
CREATE INDEX IF NOT EXISTS idx_risk_flags_detected ON universe_risk_flags(detected_at);

-- Comments for documentation
COMMENT ON TABLE catalyst_tiers IS 'Reference table defining catalyst tier classifications and expected impact ranges';
COMMENT ON TABLE universe_risk_flags IS 'Stocks flagged for exclusion from universe due to distress signals (reverse splits, delisting risk, etc)';

COMMENT ON COLUMN forward_catalysts.tier IS 'Catalyst tier: 1=Systemic (+100-500%), 2=Acceleration (+20-50%), 3=Structural (volatile)';
COMMENT ON COLUMN forward_catalysts.tier_name IS 'Human-readable tier classification (from catalyst_tiers)';
COMMENT ON COLUMN forward_catalysts.event_date IS 'Parsed event date from expected_window for sorting/filtering';
COMMENT ON COLUMN forward_catalysts.confidence_score IS 'Confidence 0.0-1.0 based on source quality (1.0=official filing, 0.6=management hint)';
COMMENT ON COLUMN forward_catalysts.sector_targeted IS 'TRUE if found via sector-specific scan, FALSE if generic universe scan';
COMMENT ON COLUMN forward_catalysts.last_verified_at IS 'Timestamp of last verification (for re-scan prioritization)';

COMMENT ON COLUMN universe_risk_flags.flag_type IS 'Type of risk: reverse_split, delisting_risk, fraud_investigation, bankruptcy';
COMMENT ON COLUMN universe_risk_flags.flag_date IS 'Date when risk was detected';
COMMENT ON COLUMN universe_risk_flags.scheduled_date IS 'Scheduled date for event (e.g., reverse split execution date)';
COMMENT ON COLUMN universe_risk_flags.split_ratio IS 'Split ratio for reverse splits (e.g., "1:5" = 5 shares become 1)';
