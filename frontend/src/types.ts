export interface PredictedCatalyst {
  symbol: string;
  detected: boolean | null;
  event_name: string | null;
  impact_type: string | null;
  expected_window: string | null;
  strategic_summary: string | null;
  source_url: string | null;
  model: string | null;
  scanned_at: string | null;
  tier?: number | null;  // 1, 2, or 3
  tier_name?: string | null;
  event_date?: string | null;
  confidence_score?: number | null;
}

// Legacy alias for backwards compatibility
export type ForwardCatalyst = PredictedCatalyst;

export interface CompanyMetrics {
  symbol: string;
  quality_score: number | null;
  net_income: number | null;
  profit_margin: number | null;
  revenue_ttm: number | null;
  insider_score: number | null;
  insider_net_value: number | null;
  roe: number | null;
  debt_to_equity: number | null;
  current_ratio: number | null;
  fetched_at: string;
  data_as_of: string | null;
}

export interface StepChange {
  id: number;
  symbol: string;
  start_ts: string;
  end_ts: string;
  days_to_peak: number;
  trough_price: number;
  peak_price: number;
  multiplier: number;
  post_peak_retention: number | null;
  breakout_ratio: number | null;
  market_cap_usd_at_peak: number | null;
  status: "held" | "faded";
  tier: "major" | "moderate" | "minor";
  detected_at: string;
  catalyst_explanation?: StepChangeCatalyst;
}

export interface StepChangeCatalyst {
  step_change_id: number;
  headline: string | null;
  summary: string | null;
  spike_explanation: string | null;
  was_foreseeable: boolean | null;
  foreseeable_evidence: string | null;
  perplexity_citations: any | null;
  model: string | null;
  fetched_at: string;
}

export interface UpcomingEvent {
  symbol: string;
  event_ts: string;
  event_type: "earnings" | "trial_phase3" | "other";
  title: string | null;
}

// Unified company card interface
export interface CompanyCard {
  symbol: string;
  name: string;
  sector: string;
  industry: string;
  type: "future" | "past";

  // Exchange
  exchange?: string;

  // Price data
  last_close: number;
  market_cap_usd?: number;

  // Quality
  quality_score: number;

  // Strategy
  strategy_tag?: "Buy Manually" | "Watchlist" | "Pass";
  combined_score?: number;

  // Past winner metadata
  multiplier?: number;
  days_to_peak?: number;
  trough_price?: number;
  peak_price?: number;
  was_foreseeable?: boolean;

  // Catalyst data
  forward_catalyst?: ForwardCatalyst;
  predicted_catalyst?: PredictedCatalyst;
  recent_step_change?: StepChange;
  upcoming_events?: UpcomingEvent[];

  // Past winner explanations
  headline?: string;
  summary?: string;
  spike_explanation?: string;
  foreseeable_evidence?: string;
}
