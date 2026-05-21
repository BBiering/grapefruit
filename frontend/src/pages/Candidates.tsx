import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { scanCandidates } from "../api";
import type { Candidate } from "../types";

export default function Candidates() {
  const nav = useNavigate();
  const [lookback, setLookback] = useState(20);
  const [gainPct, setGainPct] = useState(1.0);
  const [volMult, setVolMult] = useState(2.0);
  const [highLookback, setHighLookback] = useState(60);
  const [rows, setRows] = useState<Candidate[]>([]);

  const mut = useMutation({
    mutationFn: () =>
      scanCandidates({
        lookback_days: lookback,
        gain_pct: gainPct,
        vol_mult: volMult,
        high_lookback: highLookback,
        limit: 100,
      }),
    onSuccess: (data) => setRows(data),
  });

  return (
    <div>
      <div className="card">
        <h2>Current candidates</h2>
        <div className="muted" style={{ marginBottom: "0.5rem" }}>
          Heuristic-only scan against cached bars. Not financial advice.
        </div>
        <div className="row">
          <label>
            Lookback (days):{" "}
            <input
              type="number"
              min={2}
              max={252}
              value={lookback}
              onChange={(e) => setLookback(Number(e.target.value))}
            />
          </label>
          <label>
            Min gain (x − 1):{" "}
            <input
              type="number"
              step={0.1}
              value={gainPct}
              onChange={(e) => setGainPct(Number(e.target.value))}
            />
          </label>
          <label>
            Volume multiple:{" "}
            <input
              type="number"
              step={0.1}
              min={1}
              value={volMult}
              onChange={(e) => setVolMult(Number(e.target.value))}
            />
          </label>
          <label>
            New high lookback:{" "}
            <input
              type="number"
              min={5}
              max={252}
              value={highLookback}
              onChange={(e) => setHighLookback(Number(e.target.value))}
            />
          </label>
          <button onClick={() => mut.mutate()} disabled={mut.isPending}>
            {mut.isPending ? "Scanning…" : "Scan"}
          </button>
        </div>
      </div>

      <table>
        <thead>
          <tr>
            <th>Symbol</th>
            <th>Close</th>
            <th>Gain</th>
            <th>Vol ratio</th>
            <th>SMA50</th>
            <th>SMA200</th>
            <th>Score</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.symbol} onClick={() => nav(`/ticker/${r.symbol}`)}>
              <td><strong>{r.symbol}</strong></td>
              <td>{r.close.toFixed(2)}</td>
              <td>{(r.gain * 100).toFixed(0)}%</td>
              <td>{r.vol_ratio.toFixed(2)}x</td>
              <td>{r.sma50.toFixed(2)}</td>
              <td>{r.sma200.toFixed(2)}</td>
              <td>{r.score.toFixed(3)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
