export interface PastCatalyst {
  start_date: string;
  date: string;
  multiplier: number;
  reason: string;
  headline: string | null;
  summary: string | null;
  spike_explanation: string | null;
  was_foreseeable: boolean | null;
  foreseeable_evidence: string | null;
}

export interface PredictedCatalyst {
  id: number;
  date: string | null;
  event_name: string | null;
  impact_pct: number | null;
  impact_type: string | null;
  confidence: "high" | "medium" | "low" | null;
  summary: string | null;
  source_url: string | null;
  outcome: "pending" | "occurred" | "missed" | "unclear";
  scanned_at: string;
}

export interface CompanyCard {
  symbol: string;
  name: string;
  exchange?: string;
  sector: string;
  industry: string;
  last_close: number;
  market_cap_usd?: number;

  // Past: most recent 5×+ event with Perplexity explanation
  past_catalyst: PastCatalyst | null;

  // Predicted: catalyst identified before its expected date
  predicted_catalyst: PredictedCatalyst | null;
  predicted_catalysts: PredictedCatalyst[];
}
