import { useMemo, useState, useEffect } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  ResponsiveContainer,
  LineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  ReferenceDot,
  CartesianGrid,
} from "recharts";
import { supabase } from "../supabase";
import type { Winner, Bar } from "../types";

function formatMoney(usd: number | null) {
  if (usd == null) return "—";
  if (usd >= 1e9) return `$${(usd / 1e9).toFixed(2)}B`;
  if (usd >= 1e6) return `$${(usd / 1e6).toFixed(0)}M`;
  return `$${usd.toFixed(0)}`;
}

// Symbols are stored as full EODHD tickers (e.g. "DRUG.US", "ACG.LSE") so they
// are unique across exchanges; the UI shows just the bare ticker.
function displaySymbol(symbol: string) {
  return symbol.includes(".") ? symbol.slice(0, symbol.lastIndexOf(".")) : symbol;
}

function exchangeOf(symbol: string) {
  return symbol.includes(".") ? symbol.slice(symbol.lastIndexOf(".") + 1) : "";
}

function formatPct(v: number | null) {
  if (v == null) return "—";
  return `${(v * 100).toFixed(0)}%`;
}

interface RawWinner
  extends Omit<Winner, "name" | "headline" | "summary" | "spike_explanation" | "was_foreseeable" | "foreseeable_evidence" | "sector" | "industry"> {
  assets: { name: string | null; sector: string | null; industry: string | null } | null;
  winner_catalysts: {
    headline: string | null;
    summary: string | null;
    spike_explanation: string | null;
    was_foreseeable: boolean | null;
    foreseeable_evidence: string | null;
  } | null;
}

async function fetchWinners(): Promise<Winner[]> {
  const { data, error } = await supabase
    .from("winners")
    .select(`
      id, symbol, start_ts, end_ts, days_to_peak,
      trough_price, peak_price, multiplier,
      post_peak_retention, breakout_ratio,
      market_cap_usd_at_peak, status, detected_at,
      assets ( name, sector, industry ),
      winner_catalysts ( headline, summary, spike_explanation, was_foreseeable, foreseeable_evidence )
    `)
    .order("multiplier", { ascending: false })
    .limit(500);
  if (error) throw error;
  return ((data ?? []) as unknown as RawWinner[]).map((r) => ({
    ...r,
    name: r.assets?.name ?? null,
    sector: r.assets?.sector ?? null,
    industry: r.assets?.industry ?? null,
    headline: r.winner_catalysts?.headline ?? null,
    summary: r.winner_catalysts?.summary ?? null,
    spike_explanation: r.winner_catalysts?.spike_explanation ?? null,
    was_foreseeable: r.winner_catalysts?.was_foreseeable ?? null,
    foreseeable_evidence: r.winner_catalysts?.foreseeable_evidence ?? null,
  }));
}

async function fetchBars(symbol: string): Promise<Bar[]> {
  const { data, error } = await supabase
    .from("bars")
    .select("ts, close")
    .eq("symbol", symbol)
    .order("ts", { ascending: true });
  if (error) throw error;
  return (data ?? []) as Bar[];
}

export default function PastWinners() {
  const [selectedId, setSelectedId] = useState<number | null>(null);

  const q = useQuery({ queryKey: ["winners"], queryFn: fetchWinners });

  const rows = useMemo(() => {
    const r = q.data ?? [];
    const sorted = [...r];
    sorted.sort((a, b) => b.multiplier - a.multiplier);
    return sorted;
  }, [q.data]);

  // Keep a valid selection as filters change.
  useEffect(() => {
    if (rows.length === 0) {
      setSelectedId(null);
    } else if (!rows.some((w) => w.id === selectedId)) {
      setSelectedId(rows[0].id);
    }
  }, [rows, selectedId]);

  const selected = useMemo(
    () => rows.find((w) => w.id === selectedId) ?? null,
    [rows, selectedId],
  );

  if (q.isLoading) return <div className="muted">Loading winners…</div>;
  if (q.error) {
    return (
      <div className="card warn">
        <strong>Failed to load winners.</strong>
        <div className="muted">{(q.error as Error).message}</div>
      </div>
    );
  }

  return (
    <div className="winners-layout">
      {/* ---- left: list ---- */}
      <aside className="winners-list">
        <div className="muted list-count">{rows.length} champions</div>
        <ul className="winner-items">
          {rows.map((w) => (
            <li
              key={w.id}
              className={w.id === selectedId ? "winner-item active" : "winner-item"}
              onClick={() => setSelectedId(w.id)}
            >
              <div className="wi-top">
                <span className="wi-symbol">{displaySymbol(w.symbol)}</span>
                <span className="wi-mult">{w.multiplier.toFixed(1)}x</span>
              </div>
              <div className="wi-name">{w.name ?? "—"}</div>
              <div className="wi-meta muted">
                {w.industry ?? w.sector ?? "—"} · {formatMoney(w.market_cap_usd_at_peak)}
              </div>
              {w.was_foreseeable != null && (
                <div className={`wi-flag ${w.was_foreseeable ? "foreseeable-yes" : "foreseeable-no"}`}>
                  {w.was_foreseeable ? "✓ Foreseeable" : "✗ Not foreseeable"}
                </div>
              )}
            </li>
          ))}
        </ul>
      </aside>

      {/* ---- right: detail ---- */}
      <section className="winner-detail">
        {selected ? <WinnerDetail w={selected} /> : <div className="muted">No winner selected.</div>}
      </section>
    </div>
  );
}

function WinnerDetail({ w }: { w: Winner }) {
  const bq = useQuery({
    queryKey: ["bars", w.symbol],
    queryFn: () => fetchBars(w.symbol),
    staleTime: 5 * 60_000,
  });

  const series = useMemo(
    () => (bq.data ?? []).map((b) => ({ ts: b.ts, close: b.close })),
    [bq.data],
  );

  const troughPoint = series.find((p) => p.ts === w.start_ts);
  const peakPoint = series.find((p) => p.ts === w.end_ts);

  return (
    <div>
      <div className="detail-head">
        <div>
          <h2 className="detail-title">
            {displaySymbol(w.symbol)}
            <span className="detail-exchange">{exchangeOf(w.symbol)}</span>
          </h2>
          <div className="muted">{w.name ?? "—"}</div>
        </div>
        <div className="detail-badges">
          {w.sector && <span className="badge">{w.sector}</span>}
          {w.industry && <span className="badge subtle">{w.industry}</span>}
        </div>
      </div>

      {/* chart */}
      <div className="card chart-card">
        {bq.isLoading ? (
          <div className="muted chart-empty">Loading price history…</div>
        ) : series.length < 2 ? (
          <div className="muted chart-empty">No price history available.</div>
        ) : (
          <ResponsiveContainer width="100%" height={320}>
            <LineChart data={series} margin={{ top: 10, right: 16, bottom: 0, left: 0 }}>
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
              />
              {troughPoint && (
                <ReferenceDot x={troughPoint.ts} y={troughPoint.close} r={5} fill="#6b6661" stroke="#fff" />
              )}
              {peakPoint && (
                <ReferenceDot x={peakPoint.ts} y={peakPoint.close} r={5} fill="#f4bd4c" stroke="#fff" />
              )}
            </LineChart>
          </ResponsiveContainer>
        )}
      </div>

      {/* key stats */}
      <div className="stats-grid">
        <Stat label="Multiplier" value={`${w.multiplier.toFixed(1)}x`} accent />
        <Stat label="Market cap @ peak" value={formatMoney(w.market_cap_usd_at_peak)} />
        <Stat label="Trough → Peak" value={`${w.start_ts} → ${w.end_ts}`} />
        <Stat label="Days to peak" value={String(w.days_to_peak)} />
        <Stat label="Catalyst" value={w.headline || "—"} />
        <Stat
          label="Foreseeable?"
          value={w.was_foreseeable == null ? "—" : w.was_foreseeable ? "Yes" : "No"}
          tone={w.was_foreseeable == null ? undefined : w.was_foreseeable ? "good" : "bad"}
        />
      </div>

      {/* explanations */}
      <div className="explanations">
        <Explanation title="Catalyst" tag={w.headline} body={w.summary} />
        <Explanation title="Spike explanation" body={w.spike_explanation} />
        <Explanation
          title="Foreseeable evidence"
          body={
            w.was_foreseeable
              ? w.foreseeable_evidence || "Marked foreseeable, but no evidence recorded."
              : w.was_foreseeable === false
              ? "Not foreseeable from public information before the spike."
              : null
          }
        />
      </div>
    </div>
  );
}

function Stat({
  label,
  value,
  accent,
  tone,
  title,
}: {
  label: string;
  value: string;
  accent?: boolean;
  tone?: "good" | "bad";
  title?: string;
}) {
  const cls = accent
    ? "stat-value accent"
    : tone
    ? `stat-value ${tone}`
    : "stat-value";
  return (
    <div className="stat" title={title}>
      <div className="stat-label">{label}</div>
      <div className={cls}>{value}</div>
    </div>
  );
}

function Explanation({
  title,
  tag,
  body,
}: {
  title: string;
  tag?: string | null;
  body: string | null;
}) {
  return (
    <div className="card explanation">
      <div className="explanation-head">
        <span className="explanation-title">{title}</span>
        {tag && <span className="badge">{tag}</span>}
      </div>
      <p className={body ? "explanation-body" : "explanation-body muted"}>
        {body ?? "—"}
      </p>
    </div>
  );
}
