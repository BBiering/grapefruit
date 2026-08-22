import { useQuery } from "@tanstack/react-query";
import { LineChart, Line, ReferenceLine, ReferenceArea, ResponsiveContainer, XAxis, YAxis, Tooltip } from "recharts";
import { supabase } from "../supabase";

interface Bar {
  ts: string;
  close: number | null;
}

interface MiniChartProps {
  symbol: string;
  pastEvent?: { start_ts: string; end_ts: string };
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

export function MiniChart({ symbol, pastEvent }: MiniChartProps) {
  const { data: bars = [] } = useQuery({
    queryKey: ["bars-mini", symbol],
    queryFn: () => fetchBars(symbol),
    staleTime: 10 * 60 * 1000,
  });

  if (!bars.length) {
    return <div className="chart-empty">No price data</div>;
  }

  return (
    <div className="chart-frame">
      <ResponsiveContainer width="100%" height={240}>
      <LineChart data={bars} margin={{ top: 8, right: 18, bottom: 8, left: 8 }}>
        <XAxis dataKey="ts" tick={{ fontSize: 10 }} minTickGap={45} tickFormatter={(value) => String(value).slice(0, 7)} />
        <YAxis width={48} tick={{ fontSize: 10 }} tickFormatter={(value) => `$${Number(value).toFixed(0)}`} />
        <Tooltip
          labelFormatter={(value) => `Date: ${value}`}
          formatter={(value) => [value == null ? "—" : `$${Number(value).toFixed(2)}`, "Close"]}
          cursor={{ stroke: "#6b6661", strokeWidth: 1, strokeDasharray: "4 3" }}
        />

        {/* Retrospective event: yellow vertical markers and highlighted event window */}
        {pastEvent && (
          <>
            <ReferenceLine x={pastEvent.start_ts} stroke="#d79d00" strokeWidth={2} />
            <ReferenceLine x={pastEvent.end_ts} stroke="#d79d00" strokeWidth={2} />
            <ReferenceArea x1={pastEvent.start_ts} x2={pastEvent.end_ts} fill="#f4bd4c" fillOpacity={0.25} />
          </>
        )}

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
      </ResponsiveContainer>
    </div>
  );
}
