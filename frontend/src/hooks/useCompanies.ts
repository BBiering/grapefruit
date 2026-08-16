import { useQuery } from "@tanstack/react-query";
import { supabase } from "../supabase";
import type { CompanyCard } from "../types";

// Active exchanges (must match EODHD's EXCHANGES list in the backend).
const ACTIVE_EXCHANGES = ["PA"];

async function fetchUniverseCompanies(): Promise<CompanyCard[]> {
  const exchangeFilter = ACTIVE_EXCHANGES.map(ex => `symbol.ilike.*.${ex}`).join(",");

  // Query assets filtered to active exchanges.
  const { data: assetsData, error: assetsError } = await supabase
    .from("assets")
    .select("symbol, name, exchange, sector, industry, market_cap_usd")
    .or(exchangeFilter)
    .limit(800);

  if (assetsError) throw assetsError;
  if (!assetsData || assetsData.length === 0) return [];

  const activeSymbols = assetsData.map(a => a.symbol);

  // Get latest close from bars for each symbol. Fetch recent rows ordered
  // by date descending, then dedup client-side (first per symbol = latest).
  // Use a high limit since .in() + .order() returns rows across all symbols.
  const { data: barsData } = await supabase
    .from("bars")
    .select("symbol, close")
    .in("symbol", activeSymbols.slice(0, 500))
    .order("ts", { ascending: false })
    .limit(5000);

  const latestPrices = new Map<string, number>();
  if (barsData) {
    for (const row of barsData) {
      if (!latestPrices.has(row.symbol)) {
        latestPrices.set(row.symbol, row.close || 0);
      }
    }
  }

  // Fetch catalysts for all active symbols.
  const { data: catalystData } = await supabase
    .from("predicted_catalysts")
    .select("symbol, detected, event_name, impact_type, expected_window, strategic_summary, source_url, model, scanned_at, tier, tier_name, event_date, confidence_score")
    .eq("detected", true)
    .in("symbol", activeSymbols.slice(0, 1000))
    .limit(500);

  const catalystsMap = new Map(
    (catalystData || []).map(c => [c.symbol, c])
  );

  // Prioritize symbols with catalysts, then fill with remaining.
  const symbolsToFetch = [
    ...Array.from(catalystsMap.keys()),
    ...activeSymbols.filter(s => !catalystsMap.has(s)),
  ].slice(0, 500);

  const { data: stepChangesData } = await supabase
    .from("step_change_history")
    .select("symbol, id, start_ts, end_ts, days_to_peak, trough_price, peak_price, multiplier, tier, status")
    .in("symbol", symbolsToFetch)
    .order("end_ts", { ascending: false });

  const recentStepChanges = new Map();
  if (stepChangesData) {
    for (const sc of stepChangesData) {
      if (!recentStepChanges.has(sc.symbol)) {
        recentStepChanges.set(sc.symbol, sc);
      }
    }
  }

  const stepChangeIds = Array.from(recentStepChanges.values()).map(sc => sc.id);
  const { data: catalystExplanations } = await supabase
    .from("step_change_catalysts")
    .select("step_change_id, headline, summary, spike_explanation, was_foreseeable, foreseeable_evidence")
    .in("step_change_id", stepChangeIds);

  const explanationsMap = new Map();
  if (catalystExplanations) {
    for (const exp of catalystExplanations) {
      explanationsMap.set(exp.step_change_id, exp);
    }
  }

  const assetsMap = new Map(assetsData.map(a => [a.symbol, a]));

  const companies: CompanyCard[] = [];

  for (const symbol of symbolsToFetch) {
    const row = assetsMap.get(symbol);
    if (!row) continue;

    const catalyst = catalystsMap.get(row.symbol) || null;
    const recentStepChange = recentStepChanges.get(row.symbol) || null;

    if (recentStepChange) {
      const explanation = explanationsMap.get(recentStepChange.id);
      if (explanation) {
        recentStepChange.catalyst_explanation = explanation;
      }
    }

    const lastClose = latestPrices.get(row.symbol) || 0;

    companies.push({
      symbol: row.symbol,
      name: row.name || row.symbol,
      sector: row.sector || "Unknown",
      industry: row.industry || "Unknown",
      last_close: lastClose,
      market_cap_usd: row.market_cap_usd ?? undefined,
      predicted_catalyst: catalyst ?? undefined,
      recent_step_change: recentStepChange ?? undefined,
      upcoming_events: [],
      exchange: row.exchange,
    });
  }

  return companies;
}

export function useCompanies() {
  return useQuery({
    queryKey: ["companies"],
    queryFn: fetchUniverseCompanies,
    staleTime: 5 * 60 * 1000,
  });
}
