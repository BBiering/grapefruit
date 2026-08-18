import { useQuery } from "@tanstack/react-query";
import { supabase } from "../supabase";
import type { CompanyCard, PastCatalyst, PredictedCatalyst } from "../types";

const ACTIVE_EXCHANGES = ["PA"];

async function fetchCompanies(): Promise<CompanyCard[]> {
  const exchangeFilter = ACTIVE_EXCHANGES.map(ex => `symbol.ilike.*.${ex}`).join(",");

  // 1. Assets (filtered to active exchanges)
  const { data: assetsData, error: assetsError } = await supabase
    .from("assets")
    .select("symbol, name, exchange, sector, industry, market_cap_usd")
    .or(exchangeFilter)
    .limit(800);

  if (assetsError) throw assetsError;
  if (!assetsData || assetsData.length === 0) return [];

  const symbols = assetsData.map(a => a.symbol);

  // 2. Latest prices from bars
  const { data: barsData } = await supabase
    .from("bars")
    .select("symbol, close")
    .in("symbol", symbols.slice(0, 500))
    .order("ts", { ascending: false })
    .limit(5000);

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
    .in("symbol", symbols.slice(0, 500))
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
    .select("symbol, detected, event_name, expected_window, impact_type, strategic_summary, source_url, confidence, expected_impact_pct")
    .eq("detected", true)
    .in("symbol", symbols.slice(0, 500))
    .order("confidence", { ascending: true }); // high first

  if (forwardError) throw forwardError;

  const forwardBySymbol = new Map<string, any>();
  if (forwardData) {
    for (const f of forwardData) {
      if (!forwardBySymbol.has(f.symbol)) forwardBySymbol.set(f.symbol, f);
    }
  }

  // 6. Build CompanyCard[]
  const companies: CompanyCard[] = [];

  for (const asset of assetsData) {
    const step = stepBySymbol.get(asset.symbol);
    const exp = step ? explanations.get(step.id) : null;
    const forward = forwardBySymbol.get(asset.symbol);

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

    const predicted_catalyst: PredictedCatalyst | null = forward ? {
      date: forward.expected_window || null,
      event_name: forward.event_name || null,
      impact_pct: forward.expected_impact_pct ?? null,
      impact_type: forward.impact_type || null,
      confidence: forward.confidence || null,
      summary: forward.strategic_summary || null,
      source_url: forward.source_url || null,
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
