import { useQuery } from "@tanstack/react-query";
import { LineChart, Line, ResponsiveContainer, ReferenceArea, ReferenceLine } from "recharts";
import { supabase } from "../supabase";
import type { WatchlistMove, ForwardCatalyst } from "../types";

interface Bar {
  ts: string;
  close: number;
}

interface MiniChartProps {
  symbol: string;
  recentMove?: WatchlistMove;
  winnerEvent?: {
    start_ts: string;
    end_ts: string;
    trough_price: number;
    peak_price: number;
  };
  catalyst?: ForwardCatalyst;
}

async function fetchBars(symbol: string, twoYearLookback: boolean = true): Promise<Bar[]> {
  let query = supabase.from("bars").select("ts, close").eq("symbol", symbol).order("ts", { ascending: true });

  if (twoYearLookback) {
    const twoYearsAgo = new Date();
    twoYearsAgo.setFullYear(twoYearsAgo.getFullYear() - 2);
    query = query.gte("ts", twoYearsAgo.toISOString().slice(0, 10));
  }

  const { data, error } = await query;
  if (error) throw error;
  return (data ?? []) as Bar[];
}

export function MiniChart({ symbol, recentMove, winnerEvent, catalyst }: MiniChartProps) {
  const { data: bars = [] } = useQuery({
    queryKey: ["bars-mini", symbol],
    queryFn: () => fetchBars(symbol, !winnerEvent), // Full history for past winners, 2yr for future
    staleTime: 10 * 60 * 1000, // 10 minutes
  });

  if (!bars.length) {
    return <div className="mini-chart loading">Loading chart...</div>;
  }

  return (
    <div className="mini-chart">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={bars} margin={{ top: 5, right: 5, bottom: 5, left: 5 }}>
          {/* Past step change overlay (yellow) */}
          {(recentMove || winnerEvent) && (
            <ReferenceArea
              x1={recentMove?.start_ts || winnerEvent?.start_ts}
              x2={recentMove?.end_ts || winnerEvent?.end_ts}
              fill="#f4bd4c"
              fillOpacity={0.15}
            />
          )}

          {/* Future catalyst overlay (blue) */}
          {catalyst?.detected && catalyst.expected_window && (
            <ReferenceLine x={catalyst.expected_window} stroke="#4c9aff" strokeDasharray="3 3" strokeWidth={1.5} />
          )}

          {/* Price line */}
          <Line
            type="monotone"
            dataKey="close"
            stroke="#e8664f"
            strokeWidth={1.5}
            dot={false}
            isAnimationActive={false}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
