import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { supabase } from "../supabase";
import type { ForwardCatalyst, WatchlistRow } from "../types";

function formatMoney(usd: number | null) {
  if (usd == null) return <span className="muted">—</span>;
  if (usd >= 1e9) return `$${(usd / 1e9).toFixed(2)}B`;
  if (usd >= 1e6) return `$${(usd / 1e6).toFixed(0)}M`;
  return `$${usd.toFixed(0)}`;
}

function formatPct(frac: number | null) {
  if (frac == null) return <span className="muted">—</span>;
  const v = frac * 100;
  return <span style={{ color: v >= 0 ? "#1f8a4c" : "#bf4f4f" }}>{v >= 0 ? "+" : ""}{v.toFixed(0)}%</span>;
}

function formatScore(s: number | null) {
  if (s == null) return <span className="muted">—</span>;
  return s.toFixed(0);
}

interface RawWatchlist {
  symbol: string;
  last_close: number | null;
  market_cap_usd: number | null;
  sector: string | null;
  industry: string | null;
  why_listed: string;
  added_at: string;
  dollar_volume: number | null;
  momentum_180d: number | null;
  momentum_score: number | null;
  quality_score: number | null;
  combined_score: number | null;
  rank: number | null;
  assets: { name: string | null } | null;
}

interface RawEvent {
  symbol: string;
  event_ts: string;
  event_type: string;
  title: string | null;
}

async function fetchFutureWinners(): Promise<WatchlistRow[]> {
  const today = new Date().toISOString().slice(0, 10);

  const [w, e, c] = await Promise.all([
    supabase
      .from("watchlist")
      .select(`
        symbol, last_close, market_cap_usd, sector, industry, why_listed, added_at,
        dollar_volume, momentum_180d, momentum_score, quality_score, combined_score, rank,
        assets ( name )
      `)
      .order("combined_score", { ascending: false, nullsFirst: false })
      .limit(500),
    supabase
      .from("upcoming_events")
      .select("symbol, event_ts, event_type, title")
      .gte("event_ts", today)
      .order("event_ts", { ascending: true })
      .limit(2000),
    supabase.from("forward_catalysts").select("*").limit(500),
  ]);

  if (w.error) throw w.error;
  if (e.error) throw e.error;
  if (c.error) throw c.error;

  const earliestBySymbol = new Map<string, RawEvent>();
  for (const ev of (e.data ?? []) as RawEvent[]) {
    if (!earliestBySymbol.has(ev.symbol)) earliestBySymbol.set(ev.symbol, ev);
  }
  const catalystBySymbol = new Map<string, ForwardCatalyst>();
  for (const fc of (c.data ?? []) as ForwardCatalyst[]) {
    catalystBySymbol.set(fc.symbol, fc);
  }

  return ((w.data ?? []) as unknown as RawWatchlist[]).map((r) => {
    const ev = earliestBySymbol.get(r.symbol);
    return {
      ...r,
      name: r.assets?.name ?? null,
      next_event_ts: ev?.event_ts ?? null,
      next_event_type: ev?.event_type ?? null,
      next_event_title: ev?.title ?? null,
      catalyst: catalystBySymbol.get(r.symbol) ?? null,
    };
  });
}

export default function FutureWinners() {
  const q = useQuery({ queryKey: ["future-winners"], queryFn: fetchFutureWinners });

  const { alerts, watchlist } = useMemo(() => {
    const rows = q.data ?? [];
    const alerts = rows
      .filter((r) => r.catalyst?.detected)
      .sort((a, b) => (b.combined_score ?? 0) - (a.combined_score ?? 0));
    const watchlist = rows
      .filter((r) => !r.catalyst?.detected)
      .sort((a, b) => (b.combined_score ?? 0) - (a.combined_score ?? 0));
    return { alerts, watchlist };
  }, [q.data]);

  if (q.isLoading) return <div className="muted">Loading look-ahead report…</div>;
  if (q.error) {
    return (
      <div className="card warn">
        <strong>Failed to load the look-ahead report.</strong>
        <div className="muted">{(q.error as Error).message}</div>
      </div>
    );
  }

  return (
    <div>
      <div className="card">
        <span className="muted">
          US small/mid-caps ($300M–$10B market cap, under $50 price, ≥50k avg daily volume),
          ranked by 180-day momentum + quality, with imminent forward catalysts
          surfaced by Perplexity. Not financial advice.
        </span>
      </div>

      <h2>🚨 Active catalyst alerts</h2>
      {alerts.length === 0 ? (
        <div className="card muted">
          No imminent catalysts detected in the current pool. Run the
          <code> scan_forward_catalysts </code> job, or check the watchlist below.
        </div>
      ) : (
        alerts.map((r) => (
          <div className="card" key={r.symbol}>
            <div className="row" style={{ justifyContent: "space-between", flexWrap: "wrap" }}>
              <strong style={{ fontSize: "1.1rem" }}>
                {r.symbol} {r.name ? <span className="muted">· {r.name}</span> : null}
              </strong>
              <span>
                {r.last_close != null ? `$${r.last_close.toFixed(2)}` : "—"} ·{" "}
                momentum {formatPct(r.momentum_180d)} · score {formatScore(r.combined_score)}
              </span>
            </div>
            <div style={{ marginTop: "0.4rem" }}>
              <strong>{r.catalyst?.impact_type ?? "Catalyst"}</strong>
              {r.catalyst?.expected_window ? ` · ${r.catalyst.expected_window}` : ""}
              {r.catalyst?.event_name ? ` · ${r.catalyst.event_name}` : ""}
            </div>
            {r.catalyst?.strategic_summary && (
              <div style={{ marginTop: "0.25rem" }}>{r.catalyst.strategic_summary}</div>
            )}
            {r.catalyst?.source_url && (
              <div style={{ marginTop: "0.25rem" }}>
                <a href={r.catalyst.source_url} target="_blank" rel="noreferrer">
                  source ↗
                </a>
              </div>
            )}
          </div>
        ))
      )}

      <h2 style={{ marginTop: "1.5rem" }}>📋 Structural watchlist</h2>
      <div className="card muted" style={{ marginBottom: "0.75rem" }}>
        {watchlist.length} names with strong momentum but no imminent binary
        catalyst found in the 90-day window. Keep on radar.
      </div>
      <table>
        <thead>
          <tr>
            <th>#</th>
            <th>Symbol</th>
            <th>Name</th>
            <th>Industry</th>
            <th>Price</th>
            <th>Mkt cap</th>
            <th>Momentum</th>
            <th>Quality</th>
            <th>Score</th>
            <th>Next earnings</th>
          </tr>
        </thead>
        <tbody>
          {watchlist.map((r) => (
            <tr key={r.symbol}>
              <td>{r.rank ?? "—"}</td>
              <td><strong>{r.symbol}</strong></td>
              <td>{r.name ?? <span className="muted">—</span>}</td>
              <td>{r.industry ?? <span className="muted">—</span>}</td>
              <td>{r.last_close != null ? `$${r.last_close.toFixed(2)}` : "—"}</td>
              <td>{formatMoney(r.market_cap_usd)}</td>
              <td>{formatPct(r.momentum_180d)}</td>
              <td>{formatScore(r.quality_score)}</td>
              <td>{formatScore(r.combined_score)}</td>
              <td>
                {r.next_event_ts ? (
                  <span>{r.next_event_ts}{r.next_event_type ? ` · ${r.next_event_type}` : ""}</span>
                ) : (
                  <span className="muted">—</span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
