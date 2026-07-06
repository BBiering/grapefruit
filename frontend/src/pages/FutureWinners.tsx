import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  ResponsiveContainer,
  LineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  ReferenceLine,
  ReferenceArea,
  CartesianGrid,
} from "recharts";
import { supabase } from "../supabase";
import type { ForwardCatalyst, WatchlistRow, WatchlistMove, Bar } from "../types";

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

// Strip .US suffix from symbols
function displaySymbol(symbol: string) {
  return symbol.includes(".") ? symbol.slice(0, symbol.lastIndexOf(".")) : symbol;
}

interface RawWatchlist {
  symbol: string;
  last_close: number | null;
  market_cap_usd: number | null;
  why_listed: string;
  added_at: string;
  dollar_volume: number | null;
  momentum_180d: number | null;
  momentum_score: number | null;
  quality_score: number | null;
  combined_score: number | null;
  rank: number | null;
  strategy_tag: "Buy Manually" | "Watchlist" | "Pass" | null;
  assets: { name: string | null; sector: string | null; industry: string | null } | null;
}

interface RawEvent {
  symbol: string;
  event_ts: string;
  event_type: string;
  title: string | null;
}

async function fetchFutureWinners(): Promise<WatchlistRow[]> {
  const today = new Date().toISOString().slice(0, 10);

  const [w, e, c, m] = await Promise.all([
    supabase
      .from("watchlist")
      .select(`
        symbol, last_close, market_cap_usd, why_listed, added_at,
        dollar_volume, momentum_180d, momentum_score, quality_score, combined_score, rank,
        strategy_tag,
        assets ( name, sector, industry )
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
    supabase.from("watchlist_moves").select("*").limit(500),
  ]);

  if (w.error) throw w.error;
  if (e.error) throw e.error;
  if (c.error) throw c.error;
  if (m.error) throw m.error;

  const earliestBySymbol = new Map<string, RawEvent>();
  for (const ev of (e.data ?? []) as RawEvent[]) {
    if (!earliestBySymbol.has(ev.symbol)) earliestBySymbol.set(ev.symbol, ev);
  }
  const catalystBySymbol = new Map<string, ForwardCatalyst>();
  for (const fc of (c.data ?? []) as ForwardCatalyst[]) {
    catalystBySymbol.set(fc.symbol, fc);
  }
  const moveBySymbol = new Map<string, WatchlistMove>();
  for (const move of (m.data ?? []) as WatchlistMove[]) {
    moveBySymbol.set(move.symbol, move);
  }

  return ((w.data ?? []) as unknown as RawWatchlist[]).map((r) => {
    const ev = earliestBySymbol.get(r.symbol);
    return {
      ...r,
      name: r.assets?.name ?? null,
      sector: r.assets?.sector ?? null,
      industry: r.assets?.industry ?? null,
      next_event_ts: ev?.event_ts ?? null,
      next_event_type: ev?.event_type ?? null,
      next_event_title: ev?.title ?? null,
      catalyst: catalystBySymbol.get(r.symbol) ?? null,
      move: moveBySymbol.get(r.symbol) ?? null,
    };
  });
}

async function fetchBars(symbol: string): Promise<Bar[]> {
  const twoYearsAgo = new Date();
  twoYearsAgo.setFullYear(twoYearsAgo.getFullYear() - 2);
  const cutoff = twoYearsAgo.toISOString().slice(0, 10);

  const { data, error } = await supabase
    .from("bars")
    .select("ts, close")
    .eq("symbol", symbol)
    .gte("ts", cutoff)
    .order("ts", { ascending: true });
  if (error) throw error;
  return (data ?? []) as Bar[];
}

export default function FutureWinners() {
  const [selectedSymbol, setSelectedSymbol] = useState<string | null>(null);

  const q = useQuery({ queryKey: ["future-winners"], queryFn: fetchFutureWinners });

  const rows = useMemo(() => {
    return (q.data ?? []).sort((a, b) => (b.combined_score ?? 0) - (a.combined_score ?? 0));
  }, [q.data]);

  const selected = useMemo(
    () => (selectedSymbol ? rows.find((r) => r.symbol === selectedSymbol) ?? null : null),
    [rows, selectedSymbol],
  );

  if (q.isLoading) return <div className="muted">Loading potential champions…</div>;
  if (q.error) {
    return (
      <div className="card warn">
        <strong>Failed to load potential champions.</strong>
        <div className="muted">{(q.error as Error).message}</div>
      </div>
    );
  }

  return (
    <div className="future-layout">
      <div className="future-cards">
        {rows.map((r) => (
          <div
            key={r.symbol}
            className={`future-card ${selected?.symbol === r.symbol ? "active" : ""}`}
            onClick={() => setSelectedSymbol(r.symbol)}
          >
            <div className="fc-header">
              <div>
                <div className="fc-symbol">{displaySymbol(r.symbol)}</div>
                <div className="fc-name">{r.name ?? "—"}</div>
              </div>
              <div className="fc-price">
                {r.last_close != null ? `$${r.last_close.toFixed(2)}` : "—"}
              </div>
            </div>

            {r.strategy_tag && (
              <div className="fc-strategy-badge">
                <StrategyBadge tag={r.strategy_tag} />
              </div>
            )}

            <div className="fc-meta">
              <span className="muted">{r.industry ?? r.sector ?? "—"}</span>
              <span className="muted">{formatMoney(r.market_cap_usd)}</span>
            </div>

            <div className="fc-strategies">
              <Strategy
                label="Momentum"
                active={r.momentum_score != null && r.momentum_score >= 70}
                value={formatScore(r.momentum_score)}
              />
              <Strategy
                label="Catalyst"
                active={r.catalyst?.detected === true}
                value={r.catalyst?.expected_window ?? "—"}
              />
              <Strategy
                label="Quality"
                active={r.quality_score != null && r.quality_score >= 70}
                value={formatScore(r.quality_score)}
              />
            </div>
          </div>
        ))}
      </div>

      {selected && (
        <div className="future-detail">
          <DetailPane row={selected} />
        </div>
      )}
    </div>
  );
}

function StrategyBadge({ tag }: { tag: "Buy Manually" | "Watchlist" | "Pass" }) {
  const colors = {
    "Buy Manually": { bg: "#1f8a4c", text: "#fff" },
    "Watchlist": { bg: "#4c9aff", text: "#fff" },
    "Pass": { bg: "#6b6661", text: "#fff" },
  };
  const style = colors[tag];
  return (
    <span
      style={{
        display: "inline-block",
        padding: "3px 8px",
        borderRadius: "4px",
        fontSize: "11px",
        fontWeight: 600,
        backgroundColor: style.bg,
        color: style.text,
        textTransform: "uppercase",
        letterSpacing: "0.5px",
      }}
    >
      {tag}
    </span>
  );
}

function Strategy({ label, active, value }: { label: string; active: boolean; value: string | JSX.Element }) {
  return (
    <div className="strategy">
      <div className={`strategy-light ${active ? "active" : ""}`} />
      <div className="strategy-content">
        <div className="strategy-label">{label}</div>
        <div className="strategy-value">{value}</div>
      </div>
    </div>
  );
}

function DetailPane({ row }: { row: WatchlistRow }) {
  const bq = useQuery({
    queryKey: ["bars-2y", row.symbol],
    queryFn: () => fetchBars(row.symbol),
    staleTime: 5 * 60_000,
  });

  const catalystPeriod = useMemo(() => {
    let startDate: string | null = null;
    let endDate: string | null = null;

    // Try to extract dates from catalyst expected_window first
    if (row.catalyst?.detected && row.catalyst.expected_window) {
      const window = row.catalyst.expected_window;

      // Case 1: Explicit date range "2026-07-30 to 2026-08-04"
      const rangeMatch = window.match(/(\d{4}-\d{2}-\d{2})\s+to\s+(\d{4}-\d{2}-\d{2})/);
      if (rangeMatch) {
        startDate = rangeMatch[1];
        endDate = rangeMatch[2];
      } else {
        // Case 2: Single date "2026-08-06"
        const singleMatch = window.match(/^(\d{4}-\d{2}-\d{2})$/);
        if (singleMatch) {
          startDate = singleMatch[1];
          endDate = null; // Single date, no range
        } else {
          // Case 3: Vague period like "Next 30-60 days (post-June 1, 2026)"
          // Try to extract duration and any date format
          const durationMatch = window.match(/(\d+)-(\d+)\s+days/i);
          const isoDateMatch = window.match(/(\d{4}-\d{2}-\d{2})/);
          const textDateMatch = window.match(/(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{1,2}),?\s+(\d{4})/i);

          if (durationMatch && (isoDateMatch || textDateMatch)) {
            const durationDays = parseInt(durationMatch[2]); // Upper bound

            let baseDate: Date;
            if (isoDateMatch) {
              baseDate = new Date(isoDateMatch[1]);
              startDate = isoDateMatch[1];
            } else if (textDateMatch) {
              // Parse text date like "June 1, 2026"
              const month = textDateMatch[1];
              const day = parseInt(textDateMatch[2]);
              const year = parseInt(textDateMatch[3]);
              baseDate = new Date(`${month} ${day}, ${year}`);
              startDate = baseDate.toISOString().slice(0, 10);
            } else {
              baseDate = new Date();
              startDate = baseDate.toISOString().slice(0, 10);
            }

            const end = new Date(baseDate);
            end.setDate(end.getDate() + durationDays);
            endDate = end.toISOString().slice(0, 10);
          } else {
            // Last resort: extract first date found (any format)
            if (isoDateMatch) {
              startDate = isoDateMatch[1];
              endDate = null;
            } else if (textDateMatch) {
              const baseDate = new Date(`${textDateMatch[1]} ${textDateMatch[2]}, ${textDateMatch[3]}`);
              startDate = baseDate.toISOString().slice(0, 10);
              endDate = null;
            }
          }
        }
      }
    }

    // Fallback to next_event_ts (earnings calendar)
    if (!startDate && row.next_event_ts) {
      startDate = row.next_event_ts.slice(0, 10);
      endDate = null;
    }

    return { startDate, endDate };
  }, [row.catalyst, row.next_event_ts]);

  const extendedSeries = useMemo(() => {
    const historicalData = (bq.data ?? []).map((b) => ({ ts: b.ts, close: b.close }));

    // Extend timeline to include catalyst dates if they're in the future
    if (historicalData.length === 0) return [];

    const lastDate = historicalData[historicalData.length - 1].ts;
    const lastDateObj = new Date(lastDate);
    const extended = [...historicalData];

    // Determine the furthest future date we need to extend to
    let targetEndDate: Date;

    if (catalystPeriod.endDate && catalystPeriod.endDate > lastDate) {
      // Extend to catalyst end date
      targetEndDate = new Date(catalystPeriod.endDate);
    } else if (catalystPeriod.startDate && catalystPeriod.startDate > lastDate) {
      // Extend to catalyst start date
      targetEndDate = new Date(catalystPeriod.startDate);
    } else {
      // No future catalyst, extend 90 days
      targetEndDate = new Date(lastDateObj);
      targetEndDate.setDate(targetEndDate.getDate() + 90);
    }

    // Fill in the timeline with placeholder points (weekly intervals to keep data manageable)
    const currentDate = new Date(lastDateObj);
    currentDate.setDate(currentDate.getDate() + 7); // Start 1 week after last bar

    while (currentDate <= targetEndDate) {
      extended.push({
        ts: currentDate.toISOString().slice(0, 10),
        close: null as any,
      });
      currentDate.setDate(currentDate.getDate() + 7); // Add 1 week at a time
    }

    // Ensure the exact target end date is included
    const targetEndStr = targetEndDate.toISOString().slice(0, 10);
    if (extended[extended.length - 1].ts !== targetEndStr) {
      extended.push({
        ts: targetEndStr,
        close: null as any,
      });
    }

    return extended;
  }, [bq.data, catalystPeriod]);

  return (
    <div>
      <div className="detail-head">
        <div>
          <h2 className="detail-title">{displaySymbol(row.symbol)}</h2>
          <div className="muted">{row.name ?? "—"}</div>
        </div>
        <div className="detail-badges">
          {row.sector && <span className="badge">{row.sector}</span>}
          {row.industry && <span className="badge subtle">{row.industry}</span>}
        </div>
      </div>

      {/* chart */}
      <div className="card chart-card">
        {bq.isLoading ? (
          <div className="muted chart-empty">Loading price history…</div>
        ) : extendedSeries.length < 2 ? (
          <div className="muted chart-empty">No price history available.</div>
        ) : (
          <ResponsiveContainer width="100%" height={320}>
            <LineChart data={extendedSeries} margin={{ top: 10, right: 16, bottom: 0, left: 0 }}>
              <CartesianGrid stroke="rgba(28,26,24,0.06)" vertical={false} />
              <XAxis
                dataKey="ts"
                tick={{ fontSize: 11, fill: "#6b6661" }}
                minTickGap={60}
                tickFormatter={(t) => String(t).slice(0, 7)}
              />
              <YAxis
                tick={{ fontSize: 11, fill: "#6b6661" }}
                width={48}
                domain={["auto", "auto"]}
              />
              <Tooltip
                formatter={(v: number) => [v.toFixed(2), "Close"]}
                labelStyle={{ color: "#1c1a18" }}
                contentStyle={{ borderRadius: 10, border: "1px solid rgba(28,26,24,0.1)" }}
              />
              <Line
                type="monotone"
                dataKey="close"
                stroke="#e8664f"
                strokeWidth={2}
                dot={false}
                connectNulls={false}
              />

              {/* Recent move that drove momentum selection */}
              {row.move && (
                <>
                  <ReferenceLine
                    x={row.move.start_ts}
                    stroke="#6b6661"
                    strokeWidth={2}
                    strokeDasharray="3 3"
                    label={{ value: "Start", position: "top", fontSize: 10, fill: "#6b6661" }}
                  />
                  <ReferenceLine
                    x={row.move.end_ts}
                    stroke="#f4bd4c"
                    strokeWidth={2}
                    strokeDasharray="3 3"
                    label={{ value: "Peak", position: "top", fontSize: 10, fill: "#f4bd4c" }}
                  />
                  <ReferenceArea
                    x1={row.move.start_ts}
                    x2={row.move.end_ts}
                    fill="#f4bd4c"
                    fillOpacity={0.15}
                  />
                </>
              )}

              {/* Future catalyst event */}
              {catalystPeriod.startDate && (
                <>
                  {catalystPeriod.endDate ? (
                    // Date range: two lines + transparent fill
                    <>
                      <ReferenceLine
                        x={catalystPeriod.startDate}
                        stroke="#4c9aff"
                        strokeWidth={2}
                        strokeDasharray="3 3"
                        label={{ value: "Catalyst Start", position: "top", fontSize: 10, fill: "#4c9aff" }}
                      />
                      <ReferenceLine
                        x={catalystPeriod.endDate}
                        stroke="#4c9aff"
                        strokeWidth={2}
                        strokeDasharray="3 3"
                        label={{ value: "Catalyst End", position: "top", fontSize: 10, fill: "#4c9aff" }}
                      />
                      <ReferenceArea
                        x1={catalystPeriod.startDate}
                        x2={catalystPeriod.endDate}
                        fill="#4c9aff"
                        fillOpacity={0.15}
                      />
                    </>
                  ) : (
                    // Single date: one solid line
                    <ReferenceLine
                      x={catalystPeriod.startDate}
                      stroke="#4c9aff"
                      strokeWidth={2}
                      label={{ value: "Catalyst", position: "top", fontSize: 10, fill: "#4c9aff" }}
                    />
                  )}
                </>
              )}
            </LineChart>
          </ResponsiveContainer>
        )}
      </div>

      {/* stats */}
      <div className="stats-grid">
        <Stat label="Price" value={row.last_close != null ? `$${row.last_close.toFixed(2)}` : "—"} />
        <Stat label="Market cap" value={formatMoney(row.market_cap_usd)} />
        <Stat label="Momentum 180d" value={formatPct(row.momentum_180d)} />
        <Stat label="Momentum score" value={formatScore(row.momentum_score)} />
        <Stat label="Quality score" value={formatScore(row.quality_score)} />
        <Stat label="Combined score" value={formatScore(row.combined_score)} accent />
      </div>

      {/* catalyst */}
      {row.catalyst?.detected && (
        <div className="card explanation">
          <div className="explanation-head">
            <span className="explanation-title">Catalyst</span>
            {row.catalyst.impact_type && <span className="badge">{row.catalyst.impact_type}</span>}
          </div>
          <div className="explanation-body">
            {row.catalyst.event_name && <strong>{row.catalyst.event_name}</strong>}
            {row.catalyst.expected_window && <div className="muted">{row.catalyst.expected_window}</div>}
            {row.catalyst.strategic_summary && <p>{row.catalyst.strategic_summary}</p>}
            {row.catalyst.source_url && (
              <a href={row.catalyst.source_url} target="_blank" rel="noreferrer">
                source ↗
              </a>
            )}
          </div>
        </div>
      )}

      {row.next_event_ts && (
        <div className="card explanation">
          <div className="explanation-head">
            <span className="explanation-title">Next earnings</span>
            {row.next_event_type && <span className="badge">{row.next_event_type}</span>}
          </div>
          <div className="explanation-body">
            <strong>{row.next_event_ts}</strong>
            {row.next_event_title && <p className="muted">{row.next_event_title}</p>}
          </div>
        </div>
      )}
    </div>
  );
}

function Stat({
  label,
  value,
  accent,
}: {
  label: string;
  value: string | JSX.Element;
  accent?: boolean;
}) {
  const cls = accent ? "stat-value accent" : "stat-value";
  return (
    <div className="stat">
      <div className="stat-label">{label}</div>
      <div className={cls}>{value}</div>
    </div>
  );
}
