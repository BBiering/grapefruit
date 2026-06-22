import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { supabase } from "../supabase";
import type { Winner } from "../types";

function formatMoney(usd: number | null) {
  if (usd == null) return <span className="muted">—</span>;
  if (usd >= 1e9) return `$${(usd / 1e9).toFixed(2)}B`;
  if (usd >= 1e6) return `$${(usd / 1e6).toFixed(0)}M`;
  return `$${usd.toFixed(0)}`;
}

function formatPct(v: number | null) {
  if (v == null) return <span className="muted">—</span>;
  return `${(v * 100).toFixed(0)}%`;
}

function formatBool(v: boolean | null) {
  if (v == null) return <span className="muted">—</span>;
  return v ? (
    <span style={{ color: "#5fbf6f" }}>Yes</span>
  ) : (
    <span style={{ color: "#bf6f6f" }}>No</span>
  );
}

interface RawWinner extends Omit<Winner, "name" | "headline" | "summary" | "was_foreseeable" | "foreseeable_evidence"> {
  assets: { name: string | null } | null;
  winner_catalysts: {
    headline: string | null;
    summary: string | null;
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
      market_cap_usd_at_peak, sector, industry, status, detected_at,
      assets ( name ),
      winner_catalysts ( headline, summary, was_foreseeable, foreseeable_evidence )
    `)
    .order("detected_at", { ascending: false })
    .limit(500);
  if (error) throw error;
  return ((data ?? []) as unknown as RawWinner[]).map((r) => ({
    ...r,
    name: r.assets?.name ?? null,
    headline: r.winner_catalysts?.headline ?? null,
    summary: r.winner_catalysts?.summary ?? null,
    was_foreseeable: r.winner_catalysts?.was_foreseeable ?? null,
    foreseeable_evidence: r.winner_catalysts?.foreseeable_evidence ?? null,
  }));
}

export default function PastWinners() {
  const [minMult, setMinMult] = useState(5);
  const [industry, setIndustry] = useState("");

  const q = useQuery({ queryKey: ["winners"], queryFn: fetchWinners });

  const rows = useMemo(() => {
    let r = q.data ?? [];
    if (minMult) r = r.filter((w) => w.multiplier >= minMult);
    if (industry) r = r.filter((w) => w.industry === industry);
    return r;
  }, [q.data, minMult, industry]);

  const industries = useMemo(() => {
    const set = new Set<string>();
    (q.data ?? []).forEach((w) => w.industry && set.add(w.industry));
    return [...set].sort();
  }, [q.data]);

  if (q.isLoading) return <div className="muted">Loading winners…</div>;
  if (q.error) {
    return (
      <div className="card" style={{ background: "#3a1f1f" }}>
        <strong>Failed to load winners.</strong>
        <div className="muted">{(q.error as Error).message}</div>
      </div>
    );
  }

  return (
    <div>
      <div className="card row" style={{ flexWrap: "wrap" }}>
        <label>
          Min multiplier:{" "}
          <input
            type="number"
            min={1}
            step={0.5}
            value={minMult}
            onChange={(e) => setMinMult(Number(e.target.value))}
          />
        </label>
        <label>
          Industry:{" "}
          <select value={industry} onChange={(e) => setIndustry(e.target.value)}>
            <option value="">All</option>
            {industries.map((i) => (
              <option key={i} value={i}>{i}</option>
            ))}
          </select>
        </label>
        <span className="muted">{rows.length} winners</span>
      </div>

      <table>
        <thead>
          <tr>
            <th>Symbol</th>
            <th>Name</th>
            <th>Industry</th>
            <th>Mkt cap @ peak</th>
            <th>Trough → Peak</th>
            <th>Days</th>
            <th>Multiplier</th>
            <th>Catalyst</th>
            <th title="Was the move foreseeable from public info before the spike?">
              Foreseeable?
            </th>
            <th>Retention</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((w) => (
            <tr key={w.id}>
              <td><strong>{w.symbol}</strong></td>
              <td>{w.name ?? <span className="muted">—</span>}</td>
              <td>{w.industry ?? <span className="muted">—</span>}</td>
              <td>{formatMoney(w.market_cap_usd_at_peak)}</td>
              <td>{w.start_ts} → {w.end_ts}</td>
              <td>{w.days_to_peak}</td>
              <td>{w.multiplier.toFixed(1)}x</td>
              <td title={w.summary ?? ""}>
                {w.headline ?? <span className="muted">—</span>}
              </td>
              <td title={w.foreseeable_evidence ?? ""}>
                {formatBool(w.was_foreseeable)}
              </td>
              <td>{formatPct(w.post_peak_retention)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
