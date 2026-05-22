import { useMemo, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useParams, useSearchParams } from "react-router-dom";
import { getBars, getCatalyst, getNews, getTickerMeta } from "../api";
import PriceChart from "../components/PriceChart";
import HeadlineList from "../components/HeadlineList";

function shiftDate(iso: string, days: number): string {
  const d = new Date(iso + "T00:00:00Z");
  d.setUTCDate(d.getUTCDate() + days);
  return d.toISOString().slice(0, 10);
}

export default function TickerDetail() {
  const { symbol } = useParams<{ symbol: string }>();
  const [params] = useSearchParams();
  const peak = params.get("peak") ?? undefined;
  const trough = params.get("trough") ?? undefined;
  const [fullHistory, setFullHistory] = useState(false);
  const qc = useQueryClient();

  const [chartStart, chartEnd] = useMemo(() => {
    if (fullHistory || !trough || !peak) return [undefined, undefined] as const;
    return [shiftDate(trough, -30), shiftDate(peak, 60)] as const;
  }, [fullHistory, trough, peak]);

  const bars = useQuery({
    queryKey: ["bars", symbol, chartStart, chartEnd],
    queryFn: () => getBars(symbol!, chartStart, chartEnd),
    enabled: !!symbol,
  });

  const meta = useQuery({
    queryKey: ["meta", symbol],
    queryFn: () => getTickerMeta(symbol!),
    enabled: !!symbol,
  });

  const catalyst = useQuery({
    queryKey: ["catalyst", symbol, peak],
    queryFn: () => getCatalyst(symbol!, peak!),
    enabled: !!symbol && !!peak,
  });

  const news = useQuery({
    queryKey: ["news", symbol, peak],
    queryFn: () => getNews(symbol!, peak!),
    enabled: !!symbol && !!peak,
  });

  const peakBar = bars.data?.find((b) => b.ts === peak);
  const troughBar = bars.data?.find((b) => b.ts === trough);

  const header = meta.data
    ? `${symbol} — ${meta.data.name ?? ""}${
        meta.data.sector || meta.data.industry
          ? ` (${[meta.data.sector, meta.data.industry].filter(Boolean).join(" / ")})`
          : ""
      }`
    : symbol;

  return (
    <div>
      <h2>{header}</h2>
      <div className="card">
        <div className="row" style={{ justifyContent: "space-between" }}>
          <span className="muted">
            {chartStart && chartEnd
              ? `Focused: ${chartStart} → ${chartEnd}`
              : "Full price history"}
          </span>
          <label>
            <input
              type="checkbox"
              checked={fullHistory}
              onChange={(e) => setFullHistory(e.target.checked)}
            />{" "}
            show full history
          </label>
        </div>
        {bars.isLoading ? (
          <div className="muted">loading bars…</div>
        ) : (
          <PriceChart
            bars={bars.data ?? []}
            trough={troughBar ? { ts: troughBar.ts, price: troughBar.close } : undefined}
            peak={peakBar ? { ts: peakBar.ts, price: peakBar.close } : undefined}
          />
        )}
      </div>

      <div className="card">
        <div className="row" style={{ justifyContent: "space-between" }}>
          <h3 style={{ margin: 0 }}>Why this stock moved</h3>
          <button
            onClick={() => qc.invalidateQueries({ queryKey: ["catalyst", symbol, peak] })}
            disabled={!peak || catalyst.isFetching}
          >
            {catalyst.isFetching ? "Loading…" : "Refresh"}
          </button>
        </div>
        <div className="muted" style={{ marginTop: "0.25rem", marginBottom: "0.75rem" }}>
          One-sentence AI explanation from Perplexity (web-grounded, cached on disk).
        </div>
        {!peak ? (
          <div className="muted">Open a hit from the Hits page to see its catalyst.</div>
        ) : catalyst.isLoading ? (
          <div className="muted">Asking Perplexity…</div>
        ) : catalyst.data?.error === "no_key" ? (
          <div>
            <strong>PERPLEXITY_API_KEY is not set.</strong> Add it to{" "}
            <code>.env</code> and restart the backend. Get a key at{" "}
            <code>https://www.perplexity.ai/settings/api</code>.
          </div>
        ) : catalyst.data?.error ? (
          <div>
            Perplexity lookup failed: <code>{catalyst.data.error}</code>. Click
            Refresh to retry, or check the backend logs for the full error.
          </div>
        ) : catalyst.data?.summary ? (
          <p style={{ margin: 0 }}>{catalyst.data.summary}</p>
        ) : (
          <div className="muted">Perplexity returned no answer.</div>
        )}
      </div>

      <div className="card">
        <h3>Headlines around {peak ?? "peak"}</h3>
        {peak ? (
          news.isLoading ? (
            <div className="muted">loading headlines…</div>
          ) : (
            <HeadlineList articles={news.data ?? []} />
          )
        ) : (
          <div className="muted">no peak date in URL</div>
        )}
      </div>
    </div>
  );
}
