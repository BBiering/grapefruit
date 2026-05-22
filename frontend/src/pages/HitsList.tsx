import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { enrichAssets, getHits, getStatus } from "../api";

function formatMarketCap(usd: number | null) {
  if (usd == null) return <span className="muted">—</span>;
  if (usd >= 1e9) return `$${(usd / 1e9).toFixed(2)}B`;
  if (usd >= 1e6) return `$${(usd / 1e6).toFixed(0)}M`;
  return `$${usd.toFixed(0)}`;
}

export default function HitsList() {
  const [minMult, setMinMult] = useState(10);
  const [windowWeeks, setWindowWeeks] = useState<number | "">("");
  const [maxDaysSincePeak, setMaxDaysSincePeak] = useState<number | "">("");
  const [minPeakRetention, setMinPeakRetention] = useState<number | "">("");
  const nav = useNavigate();
  const qc = useQueryClient();

  const query = useQuery({
    queryKey: ["hits", windowWeeks, minMult, maxDaysSincePeak, minPeakRetention],
    queryFn: () =>
      getHits({
        min_multiplier: minMult,
        window_weeks: typeof windowWeeks === "number" ? windowWeeks : undefined,
        max_days_since_peak:
          typeof maxDaysSincePeak === "number" ? maxDaysSincePeak : undefined,
        min_peak_retention:
          typeof minPeakRetention === "number" ? minPeakRetention : undefined,
      }),
  });

  const status = useQuery({
    queryKey: ["status"],
    queryFn: getStatus,
    refetchInterval: 5000,
  });

  const enrichMut = useMutation({
    mutationFn: enrichAssets,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["status"] }),
  });

  const rows = useMemo(() => query.data ?? [], [query.data]);
  const missingNames = useMemo(
    () => rows.filter((r) => !r.name).length,
    [rows]
  );

  const s = status.data;
  const showEnrichBanner = missingNames > 0 || (s && s.hit_symbols_missing_metadata > 0);

  return (
    <div>
      {showEnrichBanner && (
        <div
          className="card"
          style={{ background: s?.keys.finnhub ? "#1f2a3a" : "#3a1f1f" }}
        >
          <div className="row" style={{ justifyContent: "space-between", flexWrap: "wrap" }}>
            <span>
              {s?.keys.finnhub ? (
                <>
                  <strong>
                    {s?.hit_symbols_missing_metadata ?? missingNames} hit symbols
                  </strong>{" "}
                  are missing company name / industry. Click to backfill from
                  Finnhub (runs in background).
                </>
              ) : (
                <>
                  <strong>FINNHUB_API_KEY is not set.</strong> Add it to{" "}
                  <code>.env</code> and restart the backend to populate name /
                  industry / market cap.
                </>
              )}
            </span>
            <button
              onClick={() => enrichMut.mutate()}
              disabled={!s?.keys.finnhub || enrichMut.isPending}
            >
              {enrichMut.isPending ? "Starting…" : "Enrich now"}
            </button>
          </div>
        </div>
      )}
      <div className="card row">
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
            <th>Current $</th>
            <th>% of peak</th>
            <th>Days since peak</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((h, i) => (
            <tr key={i} onClick={() => nav(`/ticker/${h.symbol}?peak=${h.end_ts}&trough=${h.start_ts}`)}>
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
