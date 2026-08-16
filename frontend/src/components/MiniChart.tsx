import { useQuery } from "@tanstack/react-query";
import { LineChart, Line, ReferenceLine } from "recharts";
import { supabase } from "../supabase";
import type { PredictedCatalyst } from "../types";

interface Bar {
  ts: string;
  close: number;
}

interface MiniChartProps {
  symbol: string;
  catalyst?: PredictedCatalyst;
}

async function fetchBars(symbol: string): Promise<Bar[]> {
  let query = supabase.from("bars").select("ts, close").eq("symbol", symbol).order("ts", { ascending: true });

  const twoYearsAgo = new Date();
  twoYearsAgo.setFullYear(twoYearsAgo.getFullYear() - 2);
  query = query.gte("ts", twoYearsAgo.toISOString().slice(0, 10));

  const { data, error } = await query;
  if (error) throw error;
  return (data ?? []) as Bar[];
}

export function MiniChart({ symbol, catalyst }: MiniChartProps) {
  const { data: bars = [] } = useQuery({
    queryKey: ["bars-mini", symbol],
    queryFn: () => fetchBars(symbol),
    staleTime: 10 * 60 * 1000,
  });

  if (!bars.length) {
    return <div className="mini-chart loading">Loading chart...</div>;
  }

  return (
    <div className="mini-chart">
      <LineChart width={260} height={140} data={bars} margin={{ top: 5, right: 5, bottom: 5, left: 5 }}>
        {catalyst?.detected && catalyst.expected_window && (
          <ReferenceLine x={catalyst.expected_window} stroke="#4c9aff" strokeDasharray="3 3" strokeWidth={1.5} />
        )}

        <Line
          type="monotone"
          dataKey="close"
          stroke="#e8664f"
          strokeWidth={1.5}
          dot={false}
          isAnimationActive={false}
        />
      </LineChart>
    </div>
  );
}
