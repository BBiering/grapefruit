-- Migration 0007: Universe-wide quality metrics and step change history
-- Replaces legacy watchlist/winners tables with comprehensive coverage

-- Table 1: company_metrics - Quality/financial metrics for ALL universe stocks
CREATE TABLE company_metrics (
    symbol TEXT PRIMARY KEY REFERENCES assets(symbol) ON DELETE CASCADE,

    -- Financial Quality
    quality_score DOUBLE PRECISION,
    net_income DOUBLE PRECISION,
    profit_margin DOUBLE PRECISION,
    revenue_ttm DOUBLE PRECISION,

    -- Insider Activity
    insider_score DOUBLE PRECISION,
    insider_net_value DOUBLE PRECISION,

    -- Additional Quality Metrics
    roe DOUBLE PRECISION,
    debt_to_equity DOUBLE PRECISION,
    current_ratio DOUBLE PRECISION,

    -- Metadata
    fetched_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    data_as_of DATE
);

CREATE INDEX idx_company_metrics_quality ON company_metrics(quality_score DESC);
CREATE INDEX idx_company_metrics_insider ON company_metrics(insider_score DESC);

-- Table 2: step_change_history - ALL historical step changes (1.5x+ multiplier)
CREATE TABLE step_change_history (
    id BIGSERIAL PRIMARY KEY,
    symbol TEXT NOT NULL REFERENCES assets(symbol) ON DELETE CASCADE,

    -- Event Window
    start_ts DATE NOT NULL,
    end_ts DATE NOT NULL,
    days_to_peak INTEGER NOT NULL,

    -- Price Movement
    trough_price DOUBLE PRECISION NOT NULL,
    peak_price DOUBLE PRECISION NOT NULL,
    multiplier DOUBLE PRECISION NOT NULL,

    -- Quality Metrics
    post_peak_retention DOUBLE PRECISION,
    breakout_ratio DOUBLE PRECISION,
    market_cap_usd_at_peak DOUBLE PRECISION,

    -- Classification
    status TEXT CHECK (status IN ('held', 'faded')),
    tier TEXT CHECK (tier IN ('major', 'moderate', 'minor')),

    -- Metadata
    detected_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    UNIQUE (symbol, end_ts)
);

CREATE INDEX idx_step_change_symbol ON step_change_history(symbol);
CREATE INDEX idx_step_change_end_ts ON step_change_history(end_ts DESC);
CREATE INDEX idx_step_change_multiplier ON step_change_history(multiplier DESC);
CREATE INDEX idx_step_change_tier ON step_change_history(tier);

-- Table 3: step_change_catalysts - Explanations for step changes
CREATE TABLE step_change_catalysts (
    step_change_id BIGINT PRIMARY KEY REFERENCES step_change_history(id) ON DELETE CASCADE,

    -- Explanation
    headline TEXT,
    summary TEXT,
    spike_explanation TEXT,

    -- Foreseeability
    was_foreseeable BOOLEAN,
    foreseeable_evidence TEXT,

    -- Sources
    perplexity_citations JSONB,
    model TEXT,

    -- Metadata
    fetched_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_step_change_catalysts_foreseeable ON step_change_catalysts(was_foreseeable);

-- Rename forward_catalysts to predicted_catalysts
ALTER TABLE forward_catalysts RENAME TO predicted_catalysts;

-- Grant permissions (adjust schema as needed for your Supabase setup)
GRANT SELECT ON company_metrics TO anon, authenticated;
GRANT SELECT ON step_change_history TO anon, authenticated;
GRANT SELECT ON step_change_catalysts TO anon, authenticated;
GRANT SELECT ON predicted_catalysts TO anon, authenticated;
