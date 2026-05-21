import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  getJob,
  getUniverse,
  refreshBars,
  refreshUniverse,
  runScan,
} from "../api";
import ProgressBar from "../components/ProgressBar";
import type { Job } from "../types";

export default function ScanConfig() {
  const qc = useQueryClient();
  const [windowWeeks, setWindowWeeks] = useState(26);
  const [threshold, setThreshold] = useState(10);
  const [activeJobId, setActiveJobId] = useState<string | null>(null);
  const [job, setJob] = useState<Job | null>(null);

  const universe = useQuery({ queryKey: ["universe"], queryFn: getUniverse });

  const refreshUniverseMut = useMutation({
    mutationFn: refreshUniverse,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["universe"] }),
  });
  const refreshBarsMut = useMutation({
    mutationFn: () => refreshBars(5),
    onSuccess: (d) => setActiveJobId(d.job_id),
  });
  const scanMut = useMutation({
    mutationFn: () => runScan(windowWeeks, threshold),
    onSuccess: (d) => setActiveJobId(d.job_id),
  });

  useEffect(() => {
    if (!activeJobId) return;
    let cancelled = false;
    const tick = async () => {
      const j = await getJob(activeJobId);
      if (cancelled) return;
      setJob(j);
      if (j.status === "running" || j.status === "pending") {
        setTimeout(tick, 1000);
      }
    };
    tick();
    return () => {
      cancelled = true;
    };
  }, [activeJobId]);

  return (
    <div>
      <div className="card">
        <h2>Universe</h2>
        <div className="row">
          <button
            onClick={() => refreshUniverseMut.mutate()}
            disabled={refreshUniverseMut.isPending}
          >
            {refreshUniverseMut.isPending ? "Refreshing…" : "Refresh universe"}
          </button>
          <span className="muted">
            {universe.data?.count ?? 0} symbols
            {universe.data?.refreshed_at
              ? ` (refreshed ${universe.data.refreshed_at.split("T")[0]})`
              : ""}
          </span>
        </div>
      </div>

      <div className="card">
        <h2>Bars</h2>
        <div className="row">
          <button
            onClick={() => refreshBarsMut.mutate()}
            disabled={refreshBarsMut.isPending || !universe.data?.count}
          >
            Refresh bars (5y)
          </button>
          <span className="muted">
            Pulls daily bars into local DuckDB. First run takes a few minutes.
          </span>
        </div>
      </div>

      <div className="card">
        <h2>Run historical scan</h2>
        <div className="row">
          <label>
            Window (weeks):{" "}
            <input
              type="number"
              min={2}
              max={52}
              value={windowWeeks}
              onChange={(e) => setWindowWeeks(Number(e.target.value))}
            />
          </label>
          <label>
            Threshold (x):{" "}
            <input
              type="number"
              min={1.5}
              step={0.5}
              value={threshold}
              onChange={(e) => setThreshold(Number(e.target.value))}
            />
          </label>
          <button
            onClick={() => scanMut.mutate()}
            disabled={scanMut.isPending}
          >
            Run scan
          </button>
        </div>
        <div className="muted" style={{ marginTop: "0.5rem" }}>
          Finds tickers whose close/min ratio inside any rolling {windowWeeks}-week
          window reached ≥ {threshold}x.
        </div>
      </div>

      <ProgressBar job={job} />
    </div>
  );
}
