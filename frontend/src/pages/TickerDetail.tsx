import { useQuery } from "@tanstack/react-query";
import { useParams, useSearchParams } from "react-router-dom";
import { getBars, getNews } from "../api";
import PriceChart from "../components/PriceChart";
import HeadlineList from "../components/HeadlineList";

export default function TickerDetail() {
  const { symbol } = useParams<{ symbol: string }>();
  const [params] = useSearchParams();
  const peak = params.get("peak") ?? undefined;
  const trough = params.get("trough") ?? undefined;

  const bars = useQuery({
    queryKey: ["bars", symbol],
    queryFn: () => getBars(symbol!),
    enabled: !!symbol,
  });

  const news = useQuery({
    queryKey: ["news", symbol, peak],
    queryFn: () => getNews(symbol!, peak!),
    enabled: !!symbol && !!peak,
  });

  const peakBar = bars.data?.find((b) => b.ts === peak);
  const troughBar = bars.data?.find((b) => b.ts === trough);

  return (
    <div>
      <h2>{symbol}</h2>
      <div className="card">
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
