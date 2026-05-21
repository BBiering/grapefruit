import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { getHits } from "../api";

export default function HitsList() {
  const [minMult, setMinMult] = useState(10);
  const [windowWeeks, setWindowWeeks] = useState<number | "">("");
  const [maxDaysSincePeak, setMaxDaysSincePeak] = useState<number | "">("");
  const [minPeakRetention, setMinPeakRetention] = useState<number | "">("");
  const nav = useNavigate();

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

  const rows = useMemo(() => query.data ?? [], [query.data]);

  return (
    <div>
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
            <th>Sector</th>
            <th>Industry</th>
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
              <td>{h.sector ?? <span className="muted">—</span>}</td>
              <td>{h.industry ?? <span className="muted">—</span>}</td>
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
