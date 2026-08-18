-- Store measured post-event impact for prediction evaluation.
BEGIN;
ALTER TABLE forward_catalysts
    ADD COLUMN IF NOT EXISTS actual_impact_pct DOUBLE PRECISION;
COMMIT;
