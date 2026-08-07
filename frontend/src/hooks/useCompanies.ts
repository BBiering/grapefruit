import { useQuery } from "@tanstack/react-query";
import { supabase } from "../supabase";
import type { CompanyCard } from "../types";

// Active exchanges (must match EODHD's EXCHANGES list in the backend).
// Symbols with exchanges outside this list are excluded — they're stale data
// from a previous universe build and don't have fresh metrics or bars.
const ACTIVE_EXCHANGES = ["PA"];

async function fetchUniverseCompanies(): Promise<CompanyCard[]> {
  // Build a filter that matches symbols ending in ".PA" (or any active exchange).
  // Supabase JS doesn't support OR on `like`, so we use `or()` syntax.
  const exchangeFilter = ACTIVE_EXCHANGES.map(ex => `symbol.ilike.*.${ex}`).join(",");

  // Query assets first (filtered to active exchanges) so we don't pull stale
  // US or other-exchange symbols left over from a prior universe build.
  const { data: assetsData, error: assetsError } = await supabase
    .from("assets")
    .select("symbol, name, exchange, sector, industry, market_cap_usd")
    .or(exchangeFilter)
    .limit(800);

  if (assetsError) throw assetsError;
  if (!assetsData || assetsData.length === 0) return [];

  const activeSymbols = assetsData.map(a => a.symbol);

  // Now get company_metrics only for our active-exchange symbols.
  const { data: metricsData } = await supabase
    .from("company_metrics")
    .select("symbol, quality_score, insider_score, net_income, profit_margin")
    .in("symbol", activeSymbols.slice(0, 500));

  const { data: pricesData } = await supabase
    .from("latest_prices")
    .select("symbol, last_close")
    .in("symbol", activeSymbols.slice(0, 500));

  const latestPrices = new Map<string, number>();
  if (pricesData) {
    for (const row of pricesData) {
      latestPrices.set(row.symbol, row.last_close || 0);
    }
  }

  const metricsSymbols = metricsData ? metricsData.map(m => m.symbol) : [];

  const { data: catalystData } = await supabase
    .from("predicted_catalysts")
    .select("symbol, detected, event_name, impact_type, expected_window, strategic_summary, source_url, model, scanned_at, tier, tier_name, event_date, confidence_score")
    .eq("detected", true)
    .in("symbol", metricsSymbols.slice(0, 1000))
    .limit(500);

  const catalystsMap = new Map(
    (catalystData || []).map(c => [c.symbol, c])
  );

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

  const metricsMap = new Map((metricsData || []).map(m => [m.symbol, m]));

  // Build a lookup for the already-fetched assets data.
  const assetsMap = new Map(assetsData.map(a => [a.symbol, a]));

  const companies: CompanyCard[] = [];

  for (const symbol of symbolsToFetch) {
    const row = assetsMap.get(symbol);
    if (!row) continue;
    const metrics = metricsMap.get(row.symbol);
    if (!metrics) continue;

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
      type: "future",
      last_close: lastClose,
      market_cap_usd: row.market_cap_usd ?? undefined,
      quality_score: metrics?.quality_score ?? 50,
      predicted_catalyst: catalyst ?? undefined,
      forward_catalyst: catalyst ?? undefined,
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
