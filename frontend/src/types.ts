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
  spike_explanation: string | null;
  was_foreseeable: boolean | null;
  foreseeable_evidence: string | null;
}

export interface Bar {
  ts: string;
  close: number;
}

export interface ForwardCatalyst {
  symbol: string;
  detected: boolean | null;
  event_name: string | null;
  impact_type: string | null;
  expected_window: string | null;
  strategic_summary: string | null;
  source_url: string | null;
  model: string | null;
  scanned_at: string | null;
}

export interface WatchlistMove {
  symbol: string;
  start_ts: string;
  end_ts: string;
  trough_price: number;
  peak_price: number;
  multiplier: number;
  days_to_peak: number;
}

export interface WatchlistRow {
  symbol: string;
  last_close: number | null;
  market_cap_usd: number | null;
  sector: string | null;
  industry: string | null;
  why_listed: string;
  added_at: string;
  // screener scores (momentum removed from strategy)
  dollar_volume: number | null;
  quality_score: number | null;
  combined_score: number | null;
  rank: number | null;
  strategy_tag: "Buy Manually" | "Watchlist" | "Pass" | null;
  // joined from assets
  name: string | null;
  // joined from upcoming_events (nearest)
  next_event_ts: string | null;
  next_event_type: string | null;
  next_event_title: string | null;
  // joined from forward_catalysts
  catalyst: ForwardCatalyst | null;
  // joined from watchlist_moves (recent step-change event)
  move: WatchlistMove | null;
}

export interface UpcomingEvent {
  symbol: string;
  event_ts: string;
  event_type: "earnings" | "trial_phase3" | "other";
  title: string | null;
}

// Unified company card interface for both future and past companies
export interface CompanyCard {
  symbol: string;
  name: string;
  sector: string;
  industry: string;
  type: "future" | "past";

  // Price data (always present)
  last_close: number;
  market_cap_usd?: number;

  // Quality (always present)
  quality_score: number;

  // Strategy (future only)
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
  recent_move?: WatchlistMove;
  winner_event?: {
    start_ts: string;
    end_ts: string;
    trough_price: number;
    peak_price: number;
  };
  upcoming_events?: UpcomingEvent[];

  // Past winner explanations
  headline?: string;
  summary?: string;
  spike_explanation?: string;
  foreseeable_evidence?: string;
}
