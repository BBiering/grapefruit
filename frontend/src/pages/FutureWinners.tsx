import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { supabase } from "../supabase";
import type { WatchlistRow } from "../types";

function formatMoney(usd: number | null) {
  if (usd == null) return <span className="muted">—</span>;
  if (usd >= 1e9) return `$${(usd / 1e9).toFixed(2)}B`;
  if (usd >= 1e6) return `$${(usd / 1e6).toFixed(0)}M`;
  return `$${usd.toFixed(0)}`;
}

interface RawWatchlist {
  symbol: string;
  last_close: number | null;
  market_cap_usd: number | null;
  sector: string | null;
  industry: string | null;
  why_listed: string;
  added_at: string;
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

  const [w, e] = await Promise.all([
    supabase
      .from("watchlist")
      .select(`
        symbol, last_close, market_cap_usd, sector, industry, why_listed, added_at,
        assets ( name )
      `)
      .order("market_cap_usd", { ascending: false })
      .limit(500),
    supabase
      .from("upcoming_events")
      .select("symbol, event_ts, event_type, title")
      .gte("event_ts", today)
      .order("event_ts", { ascending: true })
      .limit(2000),
  ]);

  if (w.error) throw w.error;
  if (e.error) throw e.error;

  const events = (e.data ?? []) as RawEvent[];
  const earliestBySymbol = new Map<string, RawEvent>();
  for (const ev of events) {
    if (!earliestBySymbol.has(ev.symbol)) earliestBySymbol.set(ev.symbol, ev);
  }

  return ((w.data ?? []) as unknown as RawWatchlist[]).map((r) => {
    const ev = earliestBySymbol.get(r.symbol);
    return {
      ...r,
      name: r.assets?.name ?? null,
      next_event_ts: ev?.event_ts ?? null,
      next_event_type: ev?.event_type ?? null,
      next_event_title: ev?.title ?? null,
    };
  });
}

export default function FutureWinners() {
  const q = useQuery({ queryKey: ["watchlist"], queryFn: fetchFutureWinners });

  const rows = useMemo(() => {
    const r = q.data ?? [];
    // Sort: rows with an upcoming event first, ascending by event date; rows without an event after.
    return [...r].sort((a, b) => {
      if (a.next_event_ts && b.next_event_ts) {
        return a.next_event_ts.localeCompare(b.next_event_ts);
      }
      if (a.next_event_ts) return -1;
      if (b.next_event_ts) return 1;
      return (b.market_cap_usd ?? 0) - (a.market_cap_usd ?? 0);
    });
  }, [q.data]);

  if (q.isLoading) return <div className="muted">Loading watchlist…</div>;
  if (q.error) {
    return (
      <div className="card" style={{ background: "#3a1f1f" }}>
        <strong>Failed to load watchlist.</strong>
        <div className="muted">{(q.error as Error).message}</div>
      </div>
    );
  }

  return (
    <div>
      <div className="card">
        <span className="muted">
          {rows.length} candidates · small-cap (market cap $300M–$2B) · US + EU.
          Sorted by nearest upcoming event.
        </span>
      </div>
      <table>
        <thead>
          <tr>
            <th>Symbol</th>
            <th>Name</th>
            <th>Industry</th>
            <th>Last close</th>
            <th>Mkt cap</th>
            <th>Why listed</th>
            <th>Next event</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((w) => (
            <tr key={w.symbol}>
              <td><strong>{w.symbol}</strong></td>
              <td>{w.name ?? <span className="muted">—</span>}</td>
              <td>{w.industry ?? <span className="muted">—</span>}</td>
              <td>${w.last_close?.toFixed(2) ?? "—"}</td>
              <td>{formatMoney(w.market_cap_usd)}</td>
              <td>{w.why_listed}</td>
              <td>
                {w.next_event_ts ? (
                  <span>
                    <strong>{w.next_event_ts}</strong> · {w.next_event_type}
                    {w.next_event_title ? ` · ${w.next_event_title}` : ""}
                  </span>
                ) : (
                  <span className="muted">none scheduled</span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
