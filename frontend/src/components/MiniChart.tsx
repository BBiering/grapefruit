import { useQuery } from "@tanstack/react-query";
import { LineChart, Line, ReferenceLine, ReferenceArea } from "recharts";
import { supabase } from "../supabase";

interface Bar {
  ts: string;
  close: number;
}

interface MiniChartProps {
  symbol: string;
  pastEvent?: { start_ts: string; multiplier: number };
  futureDate?: string;
}

async function fetchBars(symbol: string): Promise<Bar[]> {
  const twoYearsAgo = new Date();
  twoYearsAgo.setFullYear(twoYearsAgo.getFullYear() - 2);

  const { data, error } = await supabase
    .from("bars")
    .select("ts, close")
    .eq("symbol", symbol)
    .gte("ts", twoYearsAgo.toISOString().slice(0, 10))
    .order("ts", { ascending: true });

  if (error) throw error;
  return (data ?? []) as Bar[];
}

export function MiniChart({ symbol, pastEvent, futureDate }: MiniChartProps) {
  const { data: bars = [] } = useQuery({
    queryKey: ["bars-mini", symbol],
    queryFn: () => fetchBars(symbol),
    staleTime: 10 * 60 * 1000,
  });

  if (!bars.length) {
    return <div style={{ height: 140, display: "flex", alignItems: "center", justifyContent: "center", color: "#6b6661" }}>—</div>;
  }

  return (
    <LineChart width={260} height={140} data={bars} margin={{ top: 5, right: 5, bottom: 5, left: 5 }}>
      {/* Past step change zone (yellow) */}
      {pastEvent && (
        <ReferenceArea
          x1={pastEvent.start_ts}
          x2={bars[bars.length - 1]?.ts}
          fill="#f4bd4c"
          fillOpacity={0.12}
        />
      )}

      {/* Future catalyst line (blue dashed) */}
      {futureDate && (
        <ReferenceLine x={futureDate} stroke="#4c9aff" strokeDasharray="4 3" strokeWidth={1.5} />
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
  );
}
