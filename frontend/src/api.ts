import axios from "axios";
import type { AppStatus, Article, AssetMeta, Bar, Candidate, Catalyst, Hit, Job, Universe } from "./types";

const http = axios.create({ baseURL: "" });

export async function getUniverse(): Promise<Universe> {
  const { data } = await http.get<Universe>("/api/universe");
  return data;
}

export async function refreshUniverse() {
  const { data } = await http.post("/api/universe/refresh");
  return data as { count: number; refreshed_at: string };
}

export async function refreshBars(years = 5) {
  const { data } = await http.post<{ job_id: string }>("/api/bars/refresh", { years });
  return data;
}

export async function runScan(params: {
  window_weeks: number;
  threshold: number;
  max_price_usd?: number;
  max_market_cap_usd?: number;
}) {
  const { data } = await http.post<{ job_id: string }>("/api/scan/historical", params);
  return data;
}

export async function getStatus(): Promise<AppStatus> {
  const { data } = await http.get<AppStatus>("/api/status");
  return data;
}

export async function enrichAssets() {
  const { data } = await http.post<{ job_id?: string; pending: number }>(
    "/api/assets/enrich"
  );
  return data;
}

export async function refreshMarketCaps(limit?: number) {
  const { data } = await http.post<{ job_id: string; symbols: number }>(
    "/api/assets/refresh_market_caps",
    null,
    { params: limit ? { limit } : {} }
  );
  return data;
}

export async function getJob(jobId: string): Promise<Job> {
  const { data } = await http.get<Job>(`/api/jobs/${jobId}`);
  return data;
}

export async function getHits(params: {
  window_weeks?: number;
  min_multiplier?: number;
  max_days_since_peak?: number;
  min_peak_retention?: number;
  min_breakout_ratio?: number;
  industry?: string;
}): Promise<Hit[]> {
  const { data } = await http.get<Hit[]>("/api/hits", { params });
  return data;
}

export async function getIndustries(): Promise<string[]> {
  const { data } = await http.get<string[]>("/api/industries");
  return data;
}

export async function batchCatalysts(limit = 50) {
  const { data } = await http.post<{ job_id?: string; pending: number; fetched?: number }>(
    "/api/catalyst/batch",
    null,
    { params: { limit } }
  );
  return data;
}

export async function getTickerMeta(symbol: string): Promise<AssetMeta> {
  const { data } = await http.get<AssetMeta>(`/api/tickers/${symbol}/meta`);
  return data;
}

export async function getCatalyst(
  symbol: string,
  around: string,
  opts: { start?: string; trough_price?: number; peak_price?: number; refresh?: boolean } = {}
): Promise<Catalyst> {
  const { data } = await http.get<Catalyst>(`/api/tickers/${symbol}/catalyst`, {
    params: { around, ...opts },
  });
  return data;
}

export async function getBars(symbol: string, start?: string, end?: string): Promise<Bar[]> {
  const { data } = await http.get<Bar[]>(`/api/tickers/${symbol}/bars`, {
    params: { start, end },
  });
  return data;
}

export async function getNews(symbol: string, around: string, days = 14): Promise<Article[]> {
  const { data } = await http.get<Article[]>(`/api/tickers/${symbol}/news`, {
    params: { around, days },
  });
  return data;
}

export async function scanCandidates(params: {
  lookback_days: number;
  gain_pct: number;
  vol_mult: number;
  high_lookback: number;
  limit?: number;
}): Promise<Candidate[]> {
  const { data } = await http.post<Candidate[]>("/api/candidates/scan", params);
  return data;
}
