import { useQuery } from "@tanstack/react-query";
import { supabase } from "../supabase";
import type {
  CompanyCard,
  WatchlistRow,
  Winner,
  ForwardCatalyst,
  PredictedCatalyst,
  CompanyMetrics,
  StepChange,
  StepChangeCatalyst,
  WatchlistMove,
  UpcomingEvent,
} from "../types";

// Unified data fetching hook for company cards

// Raw types from Supabase queries
interface RawWatchlist {
  symbol: string;
  last_close: number | null;
  market_cap_usd: number | null;
  sector: string | null;
  industry: string | null;
  why_listed: string;
  added_at: string;
  dollar_volume: number | null;
  quality_score: number | null;
  combined_score: number | null;
  rank: number | null;
  strategy_tag: "Buy Manually" | "Watchlist" | "Pass" | null;
  assets: { name: string | null }[];
}

interface RawWinner
  extends Omit<
    Winner,
    | "name"
    | "headline"
    | "summary"
    | "spike_explanation"
    | "was_foreseeable"
    | "foreseeable_evidence"
    | "sector"
    | "industry"
  > {
  assets: { name: string | null; sector: string | null; industry: string | null }[];
  winner_catalysts: {
    headline: string | null;
    summary: string | null;
    spike_explanation: string | null;
    was_foreseeable: boolean | null;
    foreseeable_evidence: string | null;
  }[];
}

interface RawEvent {
  symbol: string;
  event_ts: string;
  event_type: string;
  title: string | null;
}

// NEW: Fetch from assets + company_metrics (universe-wide data)
interface RawAssetWithMetrics {
  symbol: string;
  name: string | null;
  exchange: string | null;
  sector: string | null;
  industry: string | null;
  market_cap_usd: number | null;
  company_metrics: CompanyMetrics[];
  predicted_catalysts: PredictedCatalyst[];
  step_change_history: StepChange[];
}

async function fetchUniverseCompanies(): Promise<CompanyCard[]> {
  // WORKAROUND: Query company_metrics first, then assets
  // PostgREST embedding might not work correctly for our schema

  // Get all company metrics
  const { data: metricsData } = await supabase
    .from("company_metrics")
    .select("symbol, quality_score, insider_score, net_income, profit_margin")
    .limit(1000);

  console.log(`[fetchUniverseCompanies] Fetched ${metricsData?.length || 0} company_metrics`);

  if (!metricsData || metricsData.length === 0) {
    console.warn("[fetchUniverseCompanies] No company_metrics found!");
    return [];
  }

  // Get symbols that have metrics
  const symbolsWithMetrics = metricsData.map(m => m.symbol);

  // Get latest prices from materialized view
  const { data: pricesData } = await supabase
    .from("latest_prices")
    .select("symbol, last_close")
    .in('symbol', symbolsWithMetrics.slice(0, 500));

  const latestPrices = new Map<string, number>();
  if (pricesData) {
    for (const row of pricesData) {
      latestPrices.set(row.symbol, row.last_close || 0);
    }
  }

  console.log(`[fetchUniverseCompanies] Fetched prices for ${latestPrices.size} symbols from latest_prices view`);

  // First, get symbols with detected catalysts to prioritize them
  const { data: catalystData } = await supabase
    .from("predicted_catalysts")
    .select("symbol, detected, event_name, impact_type, expected_window, strategic_summary, source_url, model, scanned_at, tier, tier_name, event_date, confidence_score")
    .eq("detected", true)
    .in('symbol', symbolsWithMetrics.slice(0, 1000))
    .limit(500);

  console.log(`[fetchUniverseCompanies] Found ${catalystData?.length || 0} symbols with catalysts`);

  // Create catalyst lookup
  const catalystsMap = new Map(
    (catalystData || []).map(c => [c.symbol, c])
  );

  // Prioritize symbols with catalysts, then by market cap
  const symbolsToFetch = [
    ...Array.from(catalystsMap.keys()),  // Catalyst stocks first
    ...symbolsWithMetrics.filter(s => !catalystsMap.has(s))  // Then others
  ].slice(0, 500);

  console.log(`[fetchUniverseCompanies] Fetching ${symbolsToFetch.length} assets (${catalystsMap.size} with catalysts)`);

  // Query assets WITHOUT step_change_history to avoid duplicates
  const { data, error } = await supabase
    .from("assets")
    .select(`symbol, name, exchange, sector, industry, market_cap_usd`)
    .in('symbol', symbolsToFetch);

  if (error) {
    console.error("Supabase query error:", error);
    throw error;
  }

  console.log(`[fetchUniverseCompanies] Fetched ${data?.length || 0} unique assets`);

  // Query step changes separately to get most recent per symbol
  const { data: stepChangesData } = await supabase
    .from("step_change_history")
    .select("symbol, id, start_ts, end_ts, days_to_peak, trough_price, peak_price, multiplier, tier, status")
    .in('symbol', symbolsToFetch)
    .order('end_ts', { ascending: false });

  // Group step changes by symbol and keep most recent
  const recentStepChanges = new Map();
  if (stepChangesData) {
    for (const sc of stepChangesData) {
      if (!recentStepChanges.has(sc.symbol)) {
        recentStepChanges.set(sc.symbol, sc);
      }
    }
  }

  console.log(`[fetchUniverseCompanies] Found ${recentStepChanges.size} companies with step changes`);

  // Query step change catalysts (explanations from Perplexity)
  const stepChangeIds = Array.from(recentStepChanges.values()).map(sc => sc.id);
  const { data: catalystExplanations } = await supabase
    .from("step_change_catalysts")
    .select("step_change_id, headline, summary, spike_explanation, was_foreseeable, foreseeable_evidence")
    .in('step_change_id', stepChangeIds);

  // Map explanations by step_change_id
  const explanationsMap = new Map();
  if (catalystExplanations) {
    for (const exp of catalystExplanations) {
      explanationsMap.set(exp.step_change_id, exp);
    }
  }

  console.log(`[fetchUniverseCompanies] Found ${explanationsMap.size} step change explanations`);

  // Create metrics lookup
  const metricsMap = new Map(metricsData.map(m => [m.symbol, m]));

  const companies: CompanyCard[] = [];

  try {
    for (const row of (data ?? [])) {
    const metrics = metricsMap.get(row.symbol) || null;

    // Skip if no metrics (shouldn't happen since we filtered above)
    if (!metrics) {
      console.warn(`[fetchUniverseCompanies] ${row.symbol} missing metrics despite filter`);
      continue;
    }

    // Get catalyst from our pre-fetched map
    const catalyst = catalystsMap.get(row.symbol) || null;

    // Get the most recent step change from separate query
    const recentStepChange = recentStepChanges.get(row.symbol) || null;

    // Attach catalyst explanation if available
    if (recentStepChange) {
      const explanation = explanationsMap.get(recentStepChange.id);
      if (explanation) {
        recentStepChange.catalyst_explanation = explanation;
      }
    }

    const lastClose = latestPrices.get(row.symbol) || 0;

    const card: CompanyCard = {
      symbol: row.symbol,
      name: row.name || row.symbol,
      sector: row.sector || "Unknown",
      industry: row.industry || "Unknown",
      type: "future",
      last_close: lastClose,
      market_cap_usd: row.market_cap_usd ?? undefined,
      quality_score: metrics?.quality_score ?? 50,
      predicted_catalyst: catalyst ?? undefined,
      forward_catalyst: catalyst ?? undefined,  // Backwards compatibility
      recent_step_change: recentStepChange ?? undefined,
      upcoming_events: [],
    };

    // Debug log for specific symbols with missing data
    if (["DAR.US", "ABTC.US", "RGC.US", "RDN.US"].includes(row.symbol)) {
      console.log(`[fetchUniverseCompanies] ${row.symbol} raw data from DB:`, {
        name: row.name,
        sector: row.sector,
        industry: row.industry,
        name_is_null: row.name === null,
        sector_is_null: row.sector === null,
        industry_is_null: row.industry === null,
        catalyst: catalyst,
        recentStepChange: recentStepChange,
      });
    }

      companies.push(card);
    }
  } catch (error) {
    console.error("[fetchUniverseCompanies] Error processing assets:", error);
    throw error;
  }

  console.log(`[fetchUniverseCompanies] Returning ${companies.length} companies`);
  console.log(`[fetchUniverseCompanies] QUERY SUMMARY:
    - company_metrics: ${metricsData?.length || 0}
    - predicted_catalysts (detected=true): ${catalystsMap.size}
    - assets queried: ${symbolsToFetch.length}
    - assets returned: ${data?.length || 0}
    - step_changes queried: ${stepChangesData?.length || 0}
    - step_changes unique: ${recentStepChanges.size}
    - final companies: ${companies.length}`);

  return companies;
}

// LEGACY: Fetch watchlist data (future companies)
async function fetchWatchlist(): Promise<WatchlistRow[]> {
  const today = new Date().toISOString().slice(0, 10);

  const [w, e, c, m] = await Promise.all([
    supabase
      .from("watchlist")
      .select(
        `
        symbol, last_close, market_cap_usd, sector, industry, why_listed, added_at,
        dollar_volume, quality_score, combined_score, rank,
        strategy_tag,
        assets ( name )
      `
      )
      .order("combined_score", { ascending: false, nullsFirst: false })
      .limit(500),
    supabase
      .from("upcoming_events")
      .select("symbol, event_ts, event_type, title")
      .gte("event_ts", today)
      .order("event_ts", { ascending: true })
      .limit(2000),
    supabase.from("forward_catalysts").select("*").limit(500),
    supabase.from("watchlist_moves").select("*").limit(500),
  ]);

  if (w.error) throw w.error;
  if (e.error) throw e.error;
  if (c.error) throw c.error;
  if (m.error) throw m.error;

  // Map upcoming events by symbol (earliest per symbol)
  const earliestBySymbol = new Map<string, RawEvent>();
  for (const ev of (e.data ?? []) as RawEvent[]) {
    if (!earliestBySymbol.has(ev.symbol)) earliestBySymbol.set(ev.symbol, ev);
  }

  // Map catalysts by symbol
  const catalystBySymbol = new Map<string, ForwardCatalyst>();
  for (const fc of (c.data ?? []) as ForwardCatalyst[]) {
    catalystBySymbol.set(fc.symbol, fc);
  }

  // Map moves by symbol
  const moveBySymbol = new Map<string, WatchlistMove>();
  for (const mv of (m.data ?? []) as WatchlistMove[]) {
    moveBySymbol.set(mv.symbol, mv);
  }

  return ((w.data ?? []) as unknown as RawWatchlist[]).map((r) => {
    const ev = earliestBySymbol.get(r.symbol);
    const catalyst = catalystBySymbol.get(r.symbol);
    const move = moveBySymbol.get(r.symbol);
    const asset = r.assets[0] ?? null;
    return {
      ...r,
      sector: r.sector ?? null,
      industry: r.industry ?? null,
      name: asset?.name ?? null,
      next_event_ts: ev?.event_ts ?? null,
      next_event_type: (ev?.event_type as "earnings" | "trial_phase3" | "other") ?? null,
      next_event_title: ev?.title ?? null,
      catalyst: catalyst ?? null,
      move: move ?? null,
    };
  });
}

// Fetch winners data (past companies)
async function fetchWinners(): Promise<Winner[]> {
  const { data, error } = await supabase
    .from("winners")
    .select(
      `
      id, symbol, start_ts, end_ts, days_to_peak,
      trough_price, peak_price, multiplier,
      post_peak_retention, breakout_ratio,
      market_cap_usd_at_peak, status, detected_at,
      assets ( name, sector, industry ),
      winner_catalysts ( headline, summary, spike_explanation, was_foreseeable, foreseeable_evidence )
    `
    )
    .order("multiplier", { ascending: false })
    .limit(500);

  if (error) throw error;

  console.log(`[fetchWinners] Fetched ${data?.length || 0} rows from winners table`);

  // Deduplicate by symbol (in case joins create duplicate rows)
  const winnersBySymbol = new Map<string, RawWinner>();
  for (const row of (data ?? []) as unknown as RawWinner[]) {
    if (!winnersBySymbol.has(row.symbol)) {
      winnersBySymbol.set(row.symbol, row);
    }
  }

  console.log(`[fetchWinners] Unique winners after dedup: ${winnersBySymbol.size}`);

  return Array.from(winnersBySymbol.values()).map((r) => {
    const asset = r.assets[0] ?? null;
    const catalyst = r.winner_catalysts[0] ?? null;
    return {
      ...r,
      name: asset?.name ?? null,
      sector: asset?.sector ?? null,
      industry: asset?.industry ?? null,
      headline: catalyst?.headline ?? null,
      summary: catalyst?.summary ?? null,
      spike_explanation: catalyst?.spike_explanation ?? null,
      was_foreseeable: catalyst?.was_foreseeable ?? null,
      foreseeable_evidence: catalyst?.foreseeable_evidence ?? null,
    };
  });
}

// Transform WatchlistRow to CompanyCard (future companies)
function transformWatchlistToCard(row: WatchlistRow): CompanyCard {
  return {
    symbol: row.symbol,
    name: row.name || row.symbol,
    sector: row.sector || "Unknown",
    industry: row.industry || "Unknown",
    type: "future",
    last_close: row.last_close ?? 0,
    market_cap_usd: row.market_cap_usd ?? undefined,
    quality_score: row.quality_score ?? 50,
    strategy_tag: row.strategy_tag ?? undefined,
    combined_score: row.combined_score ?? undefined,
    forward_catalyst: row.catalyst ?? undefined,
    recent_move: row.move ?? undefined,
    upcoming_events:
      row.next_event_ts && row.next_event_type
        ? ([
            {
              symbol: row.symbol,
              event_ts: row.next_event_ts,
              event_type: row.next_event_type as "earnings" | "trial_phase3" | "other",
              title: row.next_event_title ?? null,
            },
          ] as UpcomingEvent[])
        : [],
  };
}

// Transform Winner to CompanyCard (past companies)
function transformWinnerToCard(winner: Winner): CompanyCard {
  return {
    symbol: winner.symbol,
    name: winner.name || winner.symbol,
    sector: winner.sector || "Unknown",
    industry: winner.industry || "Unknown",
    type: "past",
    last_close: winner.peak_price,
    market_cap_usd: winner.market_cap_usd_at_peak ?? undefined,
    quality_score: 50, // Neutral score for past winners (no quality data stored)
    multiplier: winner.multiplier,
    days_to_peak: winner.days_to_peak,
    trough_price: winner.trough_price,
    peak_price: winner.peak_price,
    was_foreseeable: winner.was_foreseeable ?? undefined,
    winner_event: {
      start_ts: winner.start_ts,
      end_ts: winner.end_ts,
      trough_price: winner.trough_price,
      peak_price: winner.peak_price,
    },
    headline: winner.headline ?? undefined,
    summary: winner.summary ?? undefined,
    spike_explanation: winner.spike_explanation ?? undefined,
    foreseeable_evidence: winner.foreseeable_evidence ?? undefined,
  };
}

// Feature flag: use new universe-wide schema
const USE_NEW_SCHEMA = true;  // ✅ Enabled: company_metrics populated with 2,693 stocks
const SCHEMA_VERSION = 4;  // Increment to bust cache after query changes

// Main hook: fetches and transforms companies based on filter
export function useCompanies(filter: "all" | "future" | "past" = "all") {
  console.log(`[useCompanies] Called with filter="${filter}", USE_NEW_SCHEMA=${USE_NEW_SCHEMA}, version=${SCHEMA_VERSION}`);

  return useQuery({
    queryKey: ["companies", filter, USE_NEW_SCHEMA, SCHEMA_VERSION],
    queryFn: async (): Promise<CompanyCard[]> => {
      console.log(`[useCompanies] Query function executing: filter="${filter}", USE_NEW_SCHEMA=${USE_NEW_SCHEMA}`);

      if (USE_NEW_SCHEMA && filter !== "past") {
        console.log("[useCompanies] Using NEW schema path - calling fetchUniverseCompanies()");

        // NEW: Universe-wide data from assets + company_metrics
        const universeCompanies = await fetchUniverseCompanies();

        if (filter === "future") {
          return universeCompanies;
        }

        // For "all", just return universe companies (no separate past winners)
        // Step changes are already included in universeCompanies via step_change_history
        return universeCompanies;
      }

      // LEGACY: Watchlist-based data
      console.log("[useCompanies] Using LEGACY schema path - calling fetchWatchlist()");
      const results = await Promise.all([
        filter !== "past" ? fetchWatchlist() : Promise.resolve([]),
        filter !== "future" ? fetchWinners() : Promise.resolve([]),
      ]);

      const [watchlist, winners] = results;

      const futureCards = watchlist.map(transformWatchlistToCard);
      const pastCards = winners.map(transformWinnerToCard);

      return [...futureCards, ...pastCards];
    },
    staleTime: 5 * 60 * 1000, // 5 minutes
  });
}
