import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  getJob,
  getStatus,
  getUniverse,
  refreshBars,
  refreshMarketCaps,
  refreshUniverse,
  runScan,
} from "../api";
import ProgressBar from "../components/ProgressBar";
import type { Job } from "../types";

export default function ScanConfig() {
  const qc = useQueryClient();
  const [windowWeeks, setWindowWeeks] = useState(26);
  const [threshold, setThreshold] = useState(10);
  const [maxPrice, setMaxPrice] = useState<number | "">(50);
  const [maxCapUsd, setMaxCapUsd] = useState<number | "">(2_000_000_000);
  const [activeJobId, setActiveJobId] = useState<string | null>(null);
  const [job, setJob] = useState<Job | null>(null);

  const universe = useQuery({ queryKey: ["universe"], queryFn: getUniverse });
  const status = useQuery({
    queryKey: ["status"],
    queryFn: getStatus,
    refetchInterval: job?.status === "running" ? 2000 : 10000,
  });

  const refreshUniverseMut = useMutation({
    mutationFn: refreshUniverse,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["universe"] });
      qc.invalidateQueries({ queryKey: ["status"] });
    },
  });
  const refreshBarsMut = useMutation({
    mutationFn: () => refreshBars(5),
    onSuccess: (d) => setActiveJobId(d.job_id),
  });
  const scanMut = useMutation({
    mutationFn: () =>
      runScan({
        window_weeks: windowWeeks,
        threshold,
        max_price_usd: typeof maxPrice === "number" ? maxPrice : undefined,
        max_market_cap_usd: typeof maxCapUsd === "number" ? maxCapUsd : undefined,
      }),
    onSuccess: (d) => setActiveJobId(d.job_id),
  });
  const refreshCapsMut = useMutation({
    mutationFn: () => refreshMarketCaps(),
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
      } else {
        qc.invalidateQueries({ queryKey: ["status"] });
      }
    };
    tick();
    return () => {
      cancelled = true;
    };
  }, [activeJobId, qc]);

  const s = status.data;
  const missingKey = s && (!s.keys.finnhub || !s.keys.perplexity);

  return (
    <div>
      {s && (
        <div className="card" style={{ background: missingKey ? "#3a1f1f" : undefined }}>
          <h3>Status</h3>
          <div className="row" style={{ gap: "1rem", flexWrap: "wrap" }}>
            <span>
              Keys: alpaca {s.keys.alpaca ? "✓" : "✗"} · finnhub{" "}
              {s.keys.finnhub ? "✓" : "✗"} · perplexity {s.keys.perplexity ? "✓" : "✗"}
            </span>
            <span className="muted">
              {s.universe_symbols} universe · {s.bar_symbols} with bars · {s.hits} hits ·{" "}
              {s.assets_with_name}/{s.assets} assets named ·{" "}
              {s.assets_with_market_cap} with market cap
            </span>
          </div>
          {missingKey && (
            <div className="muted" style={{ marginTop: "0.5rem" }}>
              Missing API key(s) in <code>.env</code>. Add them and restart the backend.
            </div>
          )}
        </div>
      )}

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
        <h2>Market caps (Finnhub)</h2>
        <div className="row">
          <button
            onClick={() => refreshCapsMut.mutate()}
            disabled={refreshCapsMut.isPending || !s?.keys.finnhub}
          >
            Backfill market caps
          </button>
          <span className="muted">
            Pulls name, industry, and market cap for every universe symbol.
            Finnhub free tier is 60 req/min, so ~3.5h for 12k symbols. Runs in
            background. Required before <code>max_market_cap_usd</code> filtering works.
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
          <label>
            Max last close ($, blank = any):{" "}
            <input
              type="number"
              min={1}
              step={1}
              value={maxPrice}
              onChange={(e) =>
                setMaxPrice(e.target.value === "" ? "" : Number(e.target.value))
              }
            />
          </label>
          <label>
            Max market cap ($, blank = any):{" "}
            <input
              type="number"
              min={1}
              step={100_000_000}
              value={maxCapUsd}
              onChange={(e) =>
                setMaxCapUsd(e.target.value === "" ? "" : Number(e.target.value))
              }
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
          window reached ≥ {threshold}x. Price filter is instant. Market-cap filter
          only matches symbols that have cap data loaded ({s?.assets_with_market_cap ?? 0}{" "}
          available).
        </div>
      </div>

      <ProgressBar job={job} />
    </div>
  );
}
