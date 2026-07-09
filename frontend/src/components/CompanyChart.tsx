import { useMemo } from "react";
import {
  ResponsiveContainer,
  LineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  ReferenceLine,
  ReferenceArea,
  CartesianGrid,
} from "recharts";
import type { WatchlistMove, ForwardCatalyst } from "../types";

interface Bar {
  ts: string;
  close: number | null;
}

interface CompanyChartProps {
  bars: Bar[];
  recentMove?: WatchlistMove;
  winnerEvent?: {
    start_ts: string;
    end_ts: string;
    trough_price: number;
    peak_price: number;
  };
  catalyst?: ForwardCatalyst;
}

// Parse catalyst period from expected_window text
function parseCatalystPeriod(window: string | null | undefined): { startDate: string | null; endDate: string | null } {
  if (!window) return { startDate: null, endDate: null };

  // Try to extract date range: "2026-07-30 to 2026-08-04"
  const rangeMatch = window.match(/(\d{4}-\d{2}-\d{2})\s+to\s+(\d{4}-\d{2}-\d{2})/);
  if (rangeMatch) {
    return { startDate: rangeMatch[1], endDate: rangeMatch[2] };
  }

  // Try to extract single date: "2026-08-06"
  const singleMatch = window.match(/(\d{4}-\d{2}-\d{2})/);
  if (singleMatch) {
    return { startDate: singleMatch[1], endDate: null };
  }

  return { startDate: null, endDate: null };
}

export function CompanyChart({ bars, recentMove, winnerEvent, catalyst }: CompanyChartProps) {
  const extendedData = useMemo(() => {
    if (!bars.length) return [];

    const catalystPeriod = parseCatalystPeriod(catalyst?.expected_window);
    const data = [...bars];

    // Find the furthest date we need to show
    const lastBarDate = new Date(bars[bars.length - 1].ts);
    let maxDate = new Date(lastBarDate);

    // Extend to catalyst end date if it's in the future
    if (catalystPeriod.endDate) {
      const catalystEnd = new Date(catalystPeriod.endDate);
      if (catalystEnd > maxDate) maxDate = catalystEnd;
    } else if (catalystPeriod.startDate) {
      const catalystStart = new Date(catalystPeriod.startDate);
      if (catalystStart > maxDate) maxDate = catalystStart;
    }

    // Add 30-day buffer beyond max date
    const bufferDate = new Date(maxDate);
    bufferDate.setDate(bufferDate.getDate() + 30);

    // Fill weekly placeholders up to buffer date
    const currentDate = new Date(lastBarDate);
    while (currentDate <= bufferDate) {
      currentDate.setDate(currentDate.getDate() + 7);
      data.push({
        ts: currentDate.toISOString().slice(0, 10),
        close: null, // Placeholder, won't render line
      });
    }

    return data;
  }, [bars, catalyst]);

  const catalystPeriod = useMemo(() => parseCatalystPeriod(catalyst?.expected_window), [catalyst]);

  if (!bars.length) {
    return (
      <div style={{ height: 600, display: "flex", alignItems: "center", justifyContent: "center" }}>
        <p className="muted">Loading chart...</p>
      </div>
    );
  }

  return (
    <div style={{ width: "100%", height: 600, marginBottom: "2rem" }}>
      <ResponsiveContainer>
        <LineChart data={extendedData} margin={{ top: 20, right: 30, bottom: 20, left: 10 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="rgba(107, 102, 97, 0.2)" />

          <XAxis
            dataKey="ts"
            tick={{ fontSize: 11, fill: "#6b6661" }}
            minTickGap={60}
            tickFormatter={(t) => String(t).slice(0, 7)} // "YYYY-MM"
            domain={[bars[0]?.ts, extendedData[extendedData.length - 1]?.ts]}
          />

          <YAxis
            domain={["auto", "auto"]}
            tick={{ fontSize: 11, fill: "#6b6661" }}
            tickFormatter={(v) => `$${v.toFixed(0)}`}
          />

          <Tooltip
            contentStyle={{
              background: "rgba(255, 255, 255, 0.95)",
              border: "1px solid rgba(107, 102, 97, 0.2)",
              borderRadius: "8px",
              padding: "8px 12px",
            }}
            labelFormatter={(label) => `Date: ${label}`}
            formatter={(value: any) => [`$${Number(value).toFixed(2)}`, "Price"]}
          />

          {/* Past step change overlay (yellow) */}
          {(recentMove || winnerEvent) && (
            <>
              <ReferenceLine
                x={recentMove?.start_ts || winnerEvent?.start_ts}
                stroke="#6b6661"
                strokeDasharray="3 3"
                label={{ value: "Start", position: "top", fill: "#6b6661", fontSize: 11 }}
              />
              <ReferenceLine
                x={recentMove?.end_ts || winnerEvent?.end_ts}
                stroke="#f4bd4c"
                strokeDasharray="3 3"
                label={{ value: "Peak", position: "top", fill: "#f4bd4c", fontSize: 11 }}
              />
              <ReferenceArea
                x1={recentMove?.start_ts || winnerEvent?.start_ts}
                x2={recentMove?.end_ts || winnerEvent?.end_ts}
                fill="#f4bd4c"
                fillOpacity={0.15}
              />
            </>
          )}

          {/* Future catalyst overlay (blue) */}
          {catalyst?.detected && catalystPeriod.startDate && (
            <>
              {catalystPeriod.endDate ? (
                <>
                  {/* Date range: two lines + area */}
                  <ReferenceLine
                    x={catalystPeriod.startDate}
                    stroke="#4c9aff"
                    strokeDasharray="3 3"
                    label={{ value: "Catalyst Start", position: "top", fill: "#4c9aff", fontSize: 11 }}
                  />
                  <ReferenceLine
                    x={catalystPeriod.endDate}
                    stroke="#4c9aff"
                    strokeDasharray="3 3"
                    label={{ value: "Catalyst End", position: "top", fill: "#4c9aff", fontSize: 11 }}
                  />
                  <ReferenceArea x1={catalystPeriod.startDate} x2={catalystPeriod.endDate} fill="#4c9aff" fillOpacity={0.15} />
                </>
              ) : (
                <>
                  {/* Single date: solid line */}
                  <ReferenceLine
                    x={catalystPeriod.startDate}
                    stroke="#4c9aff"
                    strokeWidth={2}
                    label={{ value: "Catalyst", position: "top", fill: "#4c9aff", fontSize: 11 }}
                  />
                </>
              )}
            </>
          )}

          {/* Price line */}
          <Line type="monotone" dataKey="close" stroke="#e8664f" strokeWidth={2} dot={false} connectNulls={false} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
