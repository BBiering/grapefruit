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

  // Get latest prices from watchlist
  const { data: pricesData } = await supabase
    .from("watchlist")
    .select("symbol, last_close");

  const latestPrices = new Map<string, number>();
  if (pricesData) {
    for (const row of pricesData) {
      latestPrices.set(row.symbol, row.last_close || 0);
    }
  }

  // Query assets for those symbols
  const { data, error } = await supabase
    .from("assets")
    .select(`
      symbol, name, exchange, sector, industry, market_cap_usd,
      predicted_catalysts ( symbol, detected, event_name, impact_type, expected_window, strategic_summary ),
      step_change_history ( id, symbol, start_ts, end_ts, days_to_peak, trough_price, peak_price, multiplier, tier, status )
    `)
    .in('symbol', symbolsWithMetrics.slice(0, 500))  // Limit to first 500 symbols with metrics
    .order('market_cap_usd', { ascending: false, nullsFirst: false });

  if (error) {
    console.error("Supabase query error:", error);
    throw error;
  }

  console.log(`[fetchUniverseCompanies] Fetched ${data?.length || 0} assets`);

  // Create metrics lookup
  const metricsMap = new Map(metricsData.map(m => [m.symbol, m]));

  const companies: CompanyCard[] = [];

  for (const row of (data ?? []) as unknown as RawAssetWithMetrics[]) {
    const metrics = metricsMap.get(row.symbol) || null;

    // Skip if no metrics (shouldn't happen since we filtered above)
    if (!metrics) {
      console.warn(`[fetchUniverseCompanies] ${row.symbol} missing metrics despite filter`);
      continue;
    }

    const catalyst = row.predicted_catalysts.find(c => c.detected) || null;

    // Get the most recent step change (by end_ts)
    const recentStepChange = row.step_change_history.length > 0
      ? [...row.step_change_history].sort((a, b) =>
          new Date(b.end_ts).getTime() - new Date(a.end_ts).getTime()
        )[0]
      : null;

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

    // Debug log for DAR.US
    if (row.symbol === "DAR.US") {
      console.log("[fetchUniverseCompanies] DAR.US data:", {
        name: row.name,
        sector: row.sector,
        industry: row.industry,
        catalyst: catalyst,
        metrics: metrics,
      });
    }

    companies.push(card);
  }

  console.log(`[fetchUniverseCompanies] Returning ${companies.length} companies`);
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

  return ((data ?? []) as unknown as RawWinner[]).map((r) => {
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

// Main hook: fetches and transforms companies based on filter
export function useCompanies(filter: "all" | "future" | "past" = "all") {
  console.log(`[useCompanies] Called with filter="${filter}", USE_NEW_SCHEMA=${USE_NEW_SCHEMA}`);

  return useQuery({
    queryKey: ["companies", filter, USE_NEW_SCHEMA],
    queryFn: async (): Promise<CompanyCard[]> => {
      console.log(`[useCompanies] Query function executing: filter="${filter}", USE_NEW_SCHEMA=${USE_NEW_SCHEMA}`);

      if (USE_NEW_SCHEMA && filter !== "past") {
        console.log("[useCompanies] Using NEW schema path - calling fetchUniverseCompanies()");

        // NEW: Universe-wide data from assets + company_metrics
        const universeCompanies = await fetchUniverseCompanies();

        if (filter === "future") {
          return universeCompanies;
        }

        // For "all", also fetch past winners
        const winners = await fetchWinners();
        const pastCards = winners.map(transformWinnerToCard);

        return [...universeCompanies, ...pastCards];
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
