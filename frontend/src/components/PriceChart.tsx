import {
  CartesianGrid,
  Line,
  LineChart,
  ReferenceDot,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { Bar } from "../types";

interface Props {
  bars: Bar[];
  trough?: { ts: string; price: number };
  peak?: { ts: string; price: number };
}

export default function PriceChart({ bars, trough, peak }: Props) {
  if (bars.length === 0) return <div className="muted">no bars cached</div>;
  return (
    <div style={{ width: "100%", height: 360 }}>
      <ResponsiveContainer>
        <LineChart data={bars} margin={{ top: 10, right: 20, left: 0, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" />
          <XAxis dataKey="ts" minTickGap={40} />
          <YAxis domain={["auto", "auto"]} />
          <Tooltip />
          <Line type="monotone" dataKey="close" stroke="#c64a1c" dot={false} />
          {trough && (
            <ReferenceDot
              x={trough.ts}
              y={trough.price}
              r={6}
              fill="#1d8a4d"
              stroke="white"
              label={{ value: "trough", position: "bottom", fontSize: 11 }}
            />
          )}
          {peak && (
            <ReferenceDot
              x={peak.ts}
              y={peak.price}
              r={6}
              fill="#c64a1c"
              stroke="white"
              label={{ value: "peak", position: "top", fontSize: 11 }}
            />
          )}
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
