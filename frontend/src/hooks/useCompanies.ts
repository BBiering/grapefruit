import { useQuery } from "@tanstack/react-query";
import { supabase } from "../supabase";
import type { CompanyCard, PastCatalyst, PredictedCatalyst, PredictionPerformance } from "../types";

// Must match eodhd_client.EXCHANGES in the backend.
const ACTIVE_EXCHANGES = ["ST", "LSE", "PA", "SW", "CO", "XETRA"];

async function fetchCompanies(): Promise<CompanyCard[]> {
  const exchangeFilter = ACTIVE_EXCHANGES.map(ex => `symbol.ilike.*.${ex}`).join(",");

  // 1. Assets (filtered to active exchanges)
  const { data: assetsData, error: assetsError } = await supabase
    .from("assets")
    .select("symbol, name, exchange, sector, industry, market_cap_usd")
    .or(exchangeFilter)
    .limit(5000);

  if (assetsError) throw assetsError;
  if (!assetsData || assetsData.length === 0) return [];

  const symbols = assetsData.map(a => a.symbol);

  // 2. Latest prices from bars
  const { data: barsData } = await supabase
    .from("bars")
    .select("symbol, close")
    .in("symbol", symbols.slice(0, 5000))
    .order("ts", { ascending: false })
    .limit(50000);

  const prices = new Map<string, number>();
  if (barsData) {
    for (const row of barsData) {
      if (!prices.has(row.symbol)) prices.set(row.symbol, row.close || 0);
    }
  }

  // 3. Past catalysts: step_change_history WHERE tier='major', most recent per symbol
  const { data: stepsData } = await supabase
    .from("step_change_history")
    .select("symbol, start_ts, end_ts, multiplier, trough_price, peak_price, id")
    .eq("tier", "major")
    .in("symbol", symbols.slice(0, 5000))
    .order("end_ts", { ascending: false });

  // Dedup: keep most recent per symbol
  const stepBySymbol = new Map<string, any>();
  if (stepsData) {
    for (const s of stepsData) {
      if (!stepBySymbol.has(s.symbol)) stepBySymbol.set(s.symbol, s);
    }
  }

  // 4. Perplexity explanations for those step changes
  const stepIds = Array.from(stepBySymbol.values()).map(s => s.id);
  const { data: explanationsData } = await supabase
    .from("step_change_catalysts")
    .select("step_change_id, headline, summary, spike_explanation, was_foreseeable, foreseeable_evidence")
    .in("step_change_id", stepIds);

  const explanations = new Map();
  if (explanationsData) {
    for (const exp of explanationsData) {
      explanations.set(exp.step_change_id, exp);
    }
  }

  // 5. Future catalysts: forward_catalysts WHERE detected=true
  const { data: forwardData, error: forwardError } = await supabase
    .from("forward_catalysts")
    .select("id, symbol, detected, event_name, expected_window, impact_type, strategic_summary, source_url, confidence, expected_impact_pct, outcome, scanned_at")
    .eq("detected", true)
    .in("symbol", symbols.slice(0, 5000))
    .order("expected_window", { ascending: false });

  if (forwardError) throw forwardError;

  const predictedBySymbol = new Map<string, PredictedCatalyst[]>();
  for (const f of forwardData || []) {
    const event: PredictedCatalyst = {
      id: f.id,
      date: f.expected_window || null,
      event_name: f.event_name || null,
      impact_pct: f.expected_impact_pct ?? null,
      impact_type: f.impact_type || null,
      confidence: f.confidence || null,
      summary: f.strategic_summary || null,
      source_url: f.source_url || null,
      outcome: f.outcome || "pending",
      scanned_at: f.scanned_at,
    };
    const events = predictedBySymbol.get(f.symbol) || [];
    events.push(event);
    predictedBySymbol.set(f.symbol, events);
  }

  // 6. Build CompanyCard[]
  const companies: CompanyCard[] = [];

  for (const asset of assetsData) {
    const step = stepBySymbol.get(asset.symbol);
    const exp = step ? explanations.get(step.id) : null;
    const predicted_catalysts = predictedBySymbol.get(asset.symbol) || [];
    const predicted_catalyst = predicted_catalysts[0] || null;

    const past_catalyst: PastCatalyst | null = step ? {
      start_date: step.start_ts,
      date: step.end_ts,
      multiplier: step.multiplier,
      reason: exp?.headline || "Unknown catalyst",
      headline: exp?.headline || null,
      summary: exp?.summary || null,
      spike_explanation: exp?.spike_explanation || null,
      was_foreseeable: exp?.was_foreseeable ?? null,
      foreseeable_evidence: exp?.foreseeable_evidence || null,
    } : null;

    companies.push({
      symbol: asset.symbol,
      name: asset.name || asset.symbol,
      exchange: asset.exchange,
      sector: asset.sector || "Unknown",
      industry: asset.industry || "Unknown",
      last_close: prices.get(asset.symbol) || 0,
      market_cap_usd: asset.market_cap_usd ?? undefined,
      past_catalyst,
      predicted_catalyst,
      predicted_catalysts,
    });
  }

  return companies;
}

export function useCompanies() {
  return useQuery({
    queryKey: ["companies"],
    queryFn: fetchCompanies,
    staleTime: 5 * 60 * 1000,
  });
}

async function fetchPredictionPerformance(): Promise<PredictionPerformance> {
  const { data, error } = await supabase
    .from("forward_catalysts")
    .select("outcome, expected_impact_pct, actual_impact_pct")
    .eq("detected", true);
  if (error) throw error;

  const rows = data || [];
  const reviewed = rows.filter((row) => row.outcome !== "pending");
  const occurred = rows.filter((row) => row.outcome === "occurred");
  const missed = rows.filter((row) => row.outcome === "missed");
  const unclear = rows.filter((row) => row.outcome === "unclear");
  const avg = (values: number[]) => values.length ? values.reduce((a, b) => a + b, 0) / values.length : null;
  const expected = rows.map((row) => row.expected_impact_pct).filter((v): v is number => typeof v === "number");
  const actual = reviewed.map((row) => row.actual_impact_pct).filter((v): v is number => typeof v === "number");

  return {
    total: rows.length,
    reviewed: reviewed.length,
    pending: rows.length - reviewed.length,
    occurred: occurred.length,
    missed: missed.length,
    unclear: unclear.length,
    hit_rate: reviewed.length ? occurred.length / reviewed.length : null,
    average_expected_pct: avg(expected),
    average_actual_pct: avg(actual),
  };
}

export function usePredictionPerformance() {
  return useQuery({
    queryKey: ["prediction-performance"],
    queryFn: fetchPredictionPerformance,
    staleTime: 5 * 60 * 1000,
  });
}
