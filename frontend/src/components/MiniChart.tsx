import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  LineChart, Line, Customized, ResponsiveContainer, XAxis, YAxis, Tooltip,
} from "recharts";
import { supabase } from "../supabase";
import type { ChartEvent } from "../types";
import { displayCatalystDate } from "../utils";

interface Bar {
  ts: string;
  close: number | null;
}

interface MiniChartProps {
  symbol: string;
  events: ChartEvent[];
}

interface Point { x: number; close: number | null; }
interface EventPoint { x: number; y: number; event: ChartEvent; }

const DAY = 86_400_000;
const FORWARD_DAYS = 190; // ~6 months, matches the catalyst scan horizon
const KIND_COLORS: Record<ChartEvent["kind"], string> = { past: "#d79d00", predicted: "#2879d0" };

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

function EventPopover({ event, dateLabel }: { event: ChartEvent; dateLabel: string }) {
  const title = event.event_name || event.headline || event.impact_type || "Catalyst";
  return (
    <div>
      <div className="ep-row">
        <span className={`ep-kind ${event.kind}`}>
          {event.kind === "past" ? "Past move" : "Predicted"}
        </span>
        <span className="ep-date">{dateLabel}</span>
      </div>
      <div className="ep-title">{title}</div>
      {event.kind === "past" && event.multiplier != null && (
        <div className="ep-meta">×{event.multiplier.toFixed(1)} move</div>
      )}
      {event.kind === "predicted" && event.impact_type && (
        <div className="ep-meta">{event.impact_type}</div>
      )}
      {event.summary && <p className="ep-summary">{event.summary}</p>}
      {event.kind === "past" && event.spike_explanation && (
        <p className="ep-summary">
          <strong>Why the spike?</strong> {event.spike_explanation}
        </p>
      )}
      {event.kind === "past" && event.was_foreseeable != null && (
        <p className="ep-summary">
          <strong>Foreseeable:</strong> {event.was_foreseeable ? "Yes" : "No"}
          {event.foreseeable_evidence ? ` — ${event.foreseeable_evidence}` : ""}
        </p>
      )}
      {event.source_url && (
        <div>
          <a href={event.source_url} target="_blank" rel="noopener noreferrer">
            View source
          </a>
        </div>
      )}
    </div>
  );
}

export function MiniChart({ symbol, events }: MiniChartProps) {
  // Hovered event + dot screen position (client coords for fixed popover).
  const [hover, setHover] = useState<{ event: ChartEvent; x: number; y: number } | null>(null);

  const { data: bars = [] } = useQuery({
    queryKey: ["bars-mini", symbol],
    queryFn: () => fetchBars(symbol),
    staleTime: 10 * 60 * 1000,
  });

  if (!bars.length) {
    return <div className="chart-empty">No price data</div>;
  }

  const points: Point[] = bars.map((b) => ({ x: Date.parse(b.ts), close: b.close }));
  const byDate = new Map<string, number>();
  for (const b of bars) if (b.close != null) byDate.set(b.ts, b.close);

  const minX = points[0].x;
  const maxX = points[points.length - 1].x;
  const lastClose = [...points].reverse().find((p) => p.close != null)?.close ?? 0;

  // y for an event: the close at/just before that date when on the chart,
  // otherwise the last close (future catalysts float at the line's end).
  const yFor = (x: number): number | null => {
    for (let d = x; d >= minX - 3 * DAY; d -= DAY) {
      const close = byDate.get(new Date(d).toISOString().slice(0, 10));
      if (close != null) return close;
    }
    return null;
  };

  const eventPoints: EventPoint[] = [];
  const seen = new Set<string>();
  for (const ev of events) {
    if (!ev.date) continue;
    const x = Date.parse(ev.date.slice(0, 10));
    if (x < minX || x > maxX + FORWARD_DAYS * DAY) continue;
    const key = `${ev.kind}:${ev.date}`;
    if (seen.has(key)) continue;
    seen.add(key);
    const yDated = yFor(x);
    const y = yDated != null ? yDated : x > maxX ? lastClose : null;
    if (y == null) continue;
    eventPoints.push({ x, y, event: ev });
  }

  const chartMax = eventPoints.reduce((m, p) => Math.max(m, p.x), maxX);

  // Drawn via Customized (recharts Scatter silently drops its data inside a
  // LineChart in 2.15): xAxis/offset give us the real scales, so we place the
  // dots ourselves and handle hover natively.
  function renderDots(state: { xAxisMap?: Record<string, { scale: (v: number) => number }>; yAxisMap?: Record<string, { scale: (v: number) => number }> }) {
    const xAxis = state.xAxisMap?.["0"];
    const yAxis = state.yAxisMap?.["0"];
    if (!xAxis || !yAxis || !eventPoints.length) return null;
    return (
      <g>
        {eventPoints.map((p) => {
          const cx = xAxis.scale(p.x);
          const cy = yAxis.scale(p.y);
          return (
            <circle
              key={p.event.id}
              cx={cx}
              cy={cy}
              r={5}
              fill={KIND_COLORS[p.event.kind]}
              stroke="#fff"
              strokeWidth={1.5}
              style={{ cursor: "pointer" }}
              onMouseEnter={(e) => {
                const rect = (e.currentTarget.ownerSVGElement as SVGSVGElement).getBoundingClientRect();
                setHover({ event: p.event, x: rect.left + cx, y: rect.top + cy });
              }}
              onMouseLeave={() => setHover(null)}
            />
          );
        })}
      </g>
    );
  }

  return (
    <div className="chart-frame">
      <ResponsiveContainer width="100%" height={240}>
        <LineChart data={points} margin={{ top: 8, right: 18, bottom: 8, left: 8 }}>
          <XAxis
            type="number"
            dataKey="x"
            domain={[minX, chartMax]}
            tick={{ fontSize: 10 }}
            minTickGap={45}
            tickFormatter={(v: number) => new Date(v).toISOString().slice(0, 7)}
          />
          <YAxis width={48} tick={{ fontSize: 10 }} tickFormatter={(v) => `$${Number(v).toFixed(0)}`} />
          <Tooltip
            labelFormatter={(value: number) => new Date(value).toISOString().slice(0, 10)}
            formatter={(value) => [value == null ? "—" : `$${Number(value).toFixed(2)}`, "Close"]}
            cursor={{ stroke: "#6b6661", strokeWidth: 1, strokeDasharray: "4 3" }}
          />
          <Line
            type="monotone"
            dataKey="close"
            stroke="#e8664f"
            strokeWidth={2}
            dot={false}
            connectNulls={false}
            isAnimationActive={false}
          />
          <Customized component={renderDots} />
        </LineChart>
      </ResponsiveContainer>

      {hover && (
        <div
          className="event-popover"
          style={{
            position: "fixed",
            left: hover.x - 20,
            top: hover.y - 14,
            transform: "translate(-100%, -100%)",
            zIndex: 60,
          }}
        >
          <EventPopover event={hover.event} dateLabel={displayCatalystDate(hover.event.date)} />
        </div>
      )}
    </div>
  );
}