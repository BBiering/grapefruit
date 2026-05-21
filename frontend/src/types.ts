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
