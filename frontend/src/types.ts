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

export interface PredictionPerformance {
  total: number;
  reviewed: number;
  pending: number;
  occurred: number;
  missed: number;
  unclear: number;
  hit_rate: number | null;
  average_expected_pct: number | null;
  average_actual_pct: number | null;
}

export interface ChartEvent {
  id: string;
  date: string | null; // ISO date for plotting; null = can't place on chart
  kind: "past" | "predicted";
  event_name: string | null;
  impact_type: string | null;
  summary: string | null;
  source_url: string | null;
  // past-only
  headline?: string | null;
  multiplier?: number | null;
  spike_explanation?: string | null;
  was_foreseeable?: boolean | null;
  foreseeable_evidence?: string | null;
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

  // Predicted: catalyst identified before its expected date (deduped)
  predicted_catalyst: PredictedCatalyst | null;
  predicted_catalysts: PredictedCatalyst[];

  // Dots rendered on the price chart, hover shows a floating window
  chart_events: ChartEvent[];

  // Epoch ms of the next predicted catalyst (quarter/half taken at their END
  // date, e.g. Q4 2027 -> 31 Dec 2027); Infinity when none is knowable.
  next_catalyst_ts: number;

  // Cached AI profile sentiment (from company_news), for the News button dot.
  news_sentiment?: "positive" | "negative" | "neutral" | null;
  news_flags?: string[] | null;
}

export interface ModelNews {
  provider: string;
  content: string;
  model: string;
  used_search: boolean;
  error?: string;
}
