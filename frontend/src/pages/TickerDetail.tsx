import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
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
        <h3>Catalyst (AI, web-grounded)</h3>
        {!peak ? (
          <div className="muted">no peak date in URL</div>
        ) : catalyst.isLoading ? (
          <div className="muted">asking Perplexity…</div>
        ) : catalyst.data?.error === "no_key" ? (
          <div className="muted">
            Set <code>PERPLEXITY_API_KEY</code> in your <code>.env</code> to enable AI catalyst explanations.
          </div>
        ) : catalyst.data?.error ? (
          <div className="muted">catalyst lookup failed: {catalyst.data.error}</div>
        ) : (
          <p>{catalyst.data?.summary}</p>
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
