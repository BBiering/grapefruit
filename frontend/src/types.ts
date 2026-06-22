export interface Winner {
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
  sector: string | null;
  industry: string | null;
  status: "held" | "faded";
  detected_at: string;
  // joined from assets
  name: string | null;
  // joined from winner_catalysts
  headline: string | null;
  summary: string | null;
  was_foreseeable: boolean | null;
  foreseeable_evidence: string | null;
}

export interface WatchlistRow {
  symbol: string;
  last_close: number | null;
  market_cap_usd: number | null;
  sector: string | null;
  industry: string | null;
  why_listed: string;
  added_at: string;
  // joined from assets
  name: string | null;
  // joined from upcoming_events (nearest)
  next_event_ts: string | null;
  next_event_type: string | null;
  next_event_title: string | null;
}
