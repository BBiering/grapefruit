import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import {
  batchCatalysts,
  enrichAssets,
  getHits,
  getIndustries,
  getStatus,
} from "../api";

function formatMarketCap(usd: number | null) {
  if (usd == null) return <span className="muted">—</span>;
  if (usd >= 1e9) return `$${(usd / 1e9).toFixed(2)}B`;
  if (usd >= 1e6) return `$${(usd / 1e6).toFixed(0)}M`;
  return `$${usd.toFixed(0)}`;
}

function formatBreakout(ratio: number | null) {
  if (ratio == null) return <span className="muted">new</span>;
  const color = ratio >= 1.5 ? "#5fbf6f" : ratio >= 1 ? "#d6b86a" : "#bf6f6f";
  return <span style={{ color }}>{ratio.toFixed(2)}x</span>;
}

function formatForeseeable(v: boolean | null) {
  if (v == null) return <span className="muted">—</span>;
  return v ? (
    <span style={{ color: "#5fbf6f" }}>Yes</span>
  ) : (
    <span style={{ color: "#bf6f6f" }}>No</span>
  );
}

export default function HitsList() {
  const [minMult, setMinMult] = useState(10);
  const [windowWeeks, setWindowWeeks] = useState<number | "">("");
  const [maxDaysSincePeak, setMaxDaysSincePeak] = useState<number | "">("");
  const [minPeakRetention, setMinPeakRetention] = useState<number | "">("");
  const [minBreakoutRatio, setMinBreakoutRatio] = useState<number | "">(1.5);
  const [industry, setIndustry] = useState<string>("");
  const nav = useNavigate();
  const qc = useQueryClient();

  const query = useQuery({
    queryKey: [
      "hits",
      windowWeeks,
      minMult,
      maxDaysSincePeak,
      minPeakRetention,
      minBreakoutRatio,
      industry,
    ],
    queryFn: () =>
      getHits({
        min_multiplier: minMult,
        window_weeks: typeof windowWeeks === "number" ? windowWeeks : undefined,
        max_days_since_peak:
          typeof maxDaysSincePeak === "number" ? maxDaysSincePeak : undefined,
        min_peak_retention:
          typeof minPeakRetention === "number" ? minPeakRetention : undefined,
        min_breakout_ratio:
          typeof minBreakoutRatio === "number" ? minBreakoutRatio : undefined,
        industry: industry || undefined,
      }),
  });

  const status = useQuery({
    queryKey: ["status"],
    queryFn: getStatus,
    refetchInterval: 5000,
  });

  const industries = useQuery({
    queryKey: ["industries"],
    queryFn: getIndustries,
  });

  const enrichMut = useMutation({
    mutationFn: enrichAssets,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["status"] }),
  });
  const catalystMut = useMutation({
    mutationFn: () => batchCatalysts(50),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["status"] });
      qc.invalidateQueries({ queryKey: ["hits"] });
    },
  });

  const rows = useMemo(() => query.data ?? [], [query.data]);
  const missingNames = useMemo(
    () => rows.filter((r) => !r.name).length,
    [rows]
  );
  const missingCatalysts = useMemo(
    () => rows.filter((r) => !r.headline).length,
    [rows]
  );

  const s = status.data;
  const showEnrichBanner = missingNames > 0 || (s && s.hit_symbols_missing_metadata > 0);
  const canFetchCatalysts = !!s?.keys?.perplexity;

  return (
    <div>
      {showEnrichBanner && (
        <div
          className="card"
          style={{ background: s?.keys?.eodhd ? "#1f2a3a" : "#3a1f1f" }}
        >
          <div className="row" style={{ justifyContent: "space-between", flexWrap: "wrap" }}>
            <span>
              {s?.keys?.eodhd ? (
                <>
                  <strong>
                    {s?.hit_symbols_missing_metadata ?? missingNames} hit symbols
                  </strong>{" "}
                  are missing company name / industry. Click to backfill from
                  EODHD (runs in background).
                </>
              ) : (
                <>
                  <strong>EODHD_API_KEY is not set.</strong> Add it to{" "}
                  <code>.env</code> and restart the backend to populate name /
                  industry / market cap.
                </>
              )}
            </span>
            <button
              onClick={() => enrichMut.mutate()}
              disabled={!s?.keys?.eodhd || enrichMut.isPending}
            >
              {enrichMut.isPending ? "Starting…" : "Enrich now"}
            </button>
          </div>
        </div>
      )}

      {missingCatalysts > 0 && (
        <div
          className="card"
          style={{ background: canFetchCatalysts ? "#1f2a3a" : "#3a1f1f" }}
        >
          <div className="row" style={{ justifyContent: "space-between", flexWrap: "wrap" }}>
            <span>
              {canFetchCatalysts ? (
                <>
                  <strong>{missingCatalysts}</strong> of the {rows.length} visible
                  hits don't have a catalyst yet. Fetch up to 50 from Perplexity
                  (background job).
                </>
              ) : (
                <>
                  <strong>PERPLEXITY_API_KEY is not set.</strong> Add it to{" "}
                  <code>.env</code> and restart to populate the Catalyst column.
                </>
              )}
            </span>
            <button
              onClick={() => catalystMut.mutate()}
              disabled={!canFetchCatalysts || catalystMut.isPending}
            >
              {catalystMut.isPending ? "Starting…" : "Fetch catalysts"}
            </button>
          </div>
        </div>
      )}

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
          Window (weeks, blank = any):{" "}
          <input
            type="number"
            min={2}
            max={52}
            value={windowWeeks}
            onChange={(e) =>
              setWindowWeeks(e.target.value === "" ? "" : Number(e.target.value))
            }
          />
        </label>
        <label>
          Max days since peak:{" "}
          <input
            type="number"
            min={1}
            value={maxDaysSincePeak}
            onChange={(e) =>
              setMaxDaysSincePeak(e.target.value === "" ? "" : Number(e.target.value))
            }
          />
        </label>
        <label>
          Min % of peak (0–1):{" "}
          <input
            type="number"
            min={0}
            max={5}
            step={0.05}
            value={minPeakRetention}
            onChange={(e) =>
              setMinPeakRetention(e.target.value === "" ? "" : Number(e.target.value))
            }
          />
        </label>
        <label title="Excludes 'crash then rebound' hits. 1.5 = peak must be ≥1.5x the max close in the 180 days before the trough.">
          Min breakout x prior-high:{" "}
          <input
            type="number"
            min={0}
            step={0.1}
            value={minBreakoutRatio}
            onChange={(e) =>
              setMinBreakoutRatio(e.target.value === "" ? "" : Number(e.target.value))
            }
          />
        </label>
        <label>
          Industry:{" "}
          <select value={industry} onChange={(e) => setIndustry(e.target.value)}>
            <option value="">All</option>
            {(industries.data ?? []).map((ind) => (
              <option key={ind} value={ind}>
                {ind}
              </option>
            ))}
          </select>
        </label>
        <span className="muted">{rows.length} hits</span>
      </div>

      <table>
        <thead>
          <tr>
            <th>Symbol</th>
            <th>Name</th>
            <th>Industry</th>
            <th>Mkt cap</th>
            <th>Window (days)</th>
            <th>Trough</th>
            <th>Peak</th>
            <th>Trough $</th>
            <th>Peak $</th>
            <th>Multiplier</th>
            <th title="peak / max close in 180d before trough; <1 = pure rebound">
              Breakout
            </th>
            <th>Catalyst</th>
            <th title="Was the move foreseeable from public info before the spike?">
              Foreseeable?
            </th>
            <th>Current $</th>
            <th>% of peak</th>
            <th>Days since peak</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((h, i) => (
            <tr
              key={i}
              onClick={() =>
                nav(`/ticker/${h.symbol}?peak=${h.end_ts}&trough=${h.start_ts}`)
              }
            >
              <td><strong>{h.symbol}</strong></td>
              <td>{h.name ?? <span className="muted">—</span>}</td>
              <td>{h.industry ?? <span className="muted">—</span>}</td>
              <td>{formatMarketCap(h.market_cap_usd)}</td>
              <td>{h.window_days}</td>
              <td>{h.start_ts}</td>
              <td>{h.end_ts}</td>
              <td>{h.trough_price.toFixed(2)}</td>
              <td>{h.peak_price.toFixed(2)}</td>
              <td>{h.multiplier.toFixed(1)}x</td>
              <td>{formatBreakout(h.breakout_ratio)}</td>
              <td title={h.catalyst_summary ?? ""}>
                {h.headline ?? <span className="muted">—</span>}
              </td>
              <td>{formatForeseeable(h.was_foreseeable)}</td>
              <td>{h.current_price != null ? h.current_price.toFixed(2) : <span className="muted">—</span>}</td>
              <td>{h.peak_retention != null ? `${(h.peak_retention * 100).toFixed(0)}%` : <span className="muted">—</span>}</td>
              <td>{h.days_since_peak ?? <span className="muted">—</span>}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
