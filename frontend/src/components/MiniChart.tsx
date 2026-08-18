import { useQuery } from "@tanstack/react-query";
import { LineChart, Line, ReferenceLine, ReferenceArea, XAxis, YAxis, Tooltip } from "recharts";
import { supabase } from "../supabase";

interface Bar {
  ts: string;
  close: number | null;
}

interface MiniChartProps {
  symbol: string;
  pastEvent?: { start_ts: string; end_ts: string };
  predictedDates?: string[];
}

async function fetchBars(symbol: string): Promise<Bar[]> {
  const threeYearsAgo = new Date();
  threeYearsAgo.setFullYear(threeYearsAgo.getFullYear() - 3);

  const { data, error } = await supabase
    .from("bars")
    .select("ts, close")
    .eq("symbol", symbol)
    .gte("ts", threeYearsAgo.toISOString().slice(0, 10))
    .order("ts", { ascending: true });

  if (error) throw error;
  return (data ?? []) as Bar[];
}

export function MiniChart({ symbol, pastEvent, predictedDates = [] }: MiniChartProps) {
  const { data: bars = [] } = useQuery({
    queryKey: ["bars-mini", symbol],
    queryFn: () => fetchBars(symbol),
    staleTime: 10 * 60 * 1000,
  });

  if (!bars.length) {
    return <div className="chart-empty">No price data</div>;
  }

  // Include a null future point so Recharts includes the predicted date in its x-axis domain.
  const chartBars = [...bars];
  for (const date of predictedDates) {
    if (date > bars[bars.length - 1].ts && !chartBars.some((bar) => bar.ts === date)) {
      chartBars.push({ ts: date, close: null });
    }
  }
  chartBars.sort((a, b) => a.ts.localeCompare(b.ts));

  return (
    <div className="chart-frame">
      <LineChart width={560} height={240} data={chartBars} margin={{ top: 8, right: 18, bottom: 8, left: 8 }}>
        <XAxis dataKey="ts" tick={{ fontSize: 10 }} minTickGap={45} tickFormatter={(value) => String(value).slice(0, 7)} />
        <YAxis width={48} tick={{ fontSize: 10 }} tickFormatter={(value) => `$${Number(value).toFixed(0)}`} />
        <Tooltip labelFormatter={(value) => `Date: ${value}`} formatter={(value) => [value == null ? "—" : `$${Number(value).toFixed(2)}`, "Close"]} />

        {/* Retrospective event: yellow vertical markers and highlighted event window */}
        {pastEvent && (
          <>
            <ReferenceLine x={pastEvent.start_ts} stroke="#d79d00" strokeWidth={2} />
            <ReferenceLine x={pastEvent.end_ts} stroke="#d79d00" strokeWidth={2} />
            <ReferenceArea x1={pastEvent.start_ts} x2={pastEvent.end_ts} fill="#f4bd4c" fillOpacity={0.25} />
          </>
        )}

        {/* Prediction: blue vertical dashed marker */}
        {predictedDates.map((date) => (
          <ReferenceLine key={date} x={date} stroke="#2879d0" strokeDasharray="6 4" strokeWidth={2} />
        ))}

        <Line
          type="monotone"
          dataKey="close"
          stroke="#e8664f"
          strokeWidth={2}
          dot={false}
          connectNulls={false}
          isAnimationActive={false}
        />
      </LineChart>
      <div className="chart-legend">
        <span className="legend-past">━ Past catalyst</span>
        <span className="legend-predicted">┆ Predicted catalyst</span>
      </div>
    </div>
  );
}
