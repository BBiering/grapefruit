export interface Hit {
  symbol: string;
  window_days: number;
  threshold: number;
  start_ts: string;
  end_ts: string;
  trough_price: number;
  peak_price: number;
  multiplier: number;
  scanned_at: string | null;
  name: string | null;
  exchange: string | null;
  sector: string | null;
  industry: string | null;
  market_cap_usd: number | null;
  current_price: number | null;
  last_ts: string | null;
  days_since_peak: number | null;
  peak_retention: number | null;
}

export interface AssetMeta {
  symbol: string;
  name: string | null;
  exchange: string | null;
  sector: string | null;
  industry: string | null;
  market_cap_usd: number | null;
  refreshed_at: string | null;
}

export interface AppStatus {
  keys: { alpaca: boolean; finnhub: boolean; perplexity: boolean };
  universe_symbols: number;
  universe_refreshed_at: string | null;
  bar_symbols: number;
  hits: number;
  assets: number;
  assets_with_name: number;
  assets_with_market_cap: number;
  hit_symbols_missing_metadata: number;
}

export interface Catalyst {
  summary: string;
  fetched_at: string;
  model: string;
  error?: string;
}

export interface Bar {
  ts: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export interface Article {
  ts: string | null;
  headline: string;
  summary: string;
  url: string;
  source: string;
}

export interface Candidate {
  symbol: string;
  close: number;
  gain: number;
  vol_ratio: number;
  sma50: number;
  sma200: number;
  score: number;
  as_of: string;
}

export interface Job {
  job_id: string;
  kind: string;
  status: "pending" | "running" | "done" | "error";
  processed: number;
  total: number;
  message: string;
  result: unknown;
  error: string | null;
  created_at: string;
}

export interface Universe {
  symbols: string[];
  count: number;
  refreshed_at: string | null;
}
