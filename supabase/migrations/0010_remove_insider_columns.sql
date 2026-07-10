-- Migration 0010: Remove insider trading columns (US-only feature)
-- Insider trading data (SEC Form 4) doesn't exist for EU stocks

-- Drop insider columns from company_metrics table
ALTER TABLE company_metrics DROP COLUMN IF EXISTS insider_score;
ALTER TABLE company_metrics DROP COLUMN IF EXISTS insider_net_value;

-- Note: This migration affects existing data but insider scores are recalculated
-- weekly anyway. EU stocks don't have SEC Form 4 data.
