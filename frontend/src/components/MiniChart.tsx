import { useQuery } from "@tanstack/react-query";
import {
  LineChart, Line, Scatter, ResponsiveContainer, XAxis, YAxis, Tooltip,
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
    <div className="event-popover">
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

// One shared tooltip: shows the floating event window over a dot, or the
// plain price popover anywhere else on the line.
function ChartTooltip({ active, payload }: { active?: boolean; payload?: Array<{ payload?: unknown }> }) {
  if (!active || !payload?.length) return null;
  const ev = payload.find((p) => (p.payload as EventPoint | undefined)?.event)?.payload as EventPoint | undefined;
  if (ev) {
    return <EventPopover event={ev.event} dateLabel={displayCatalystDate(ev.event.date)} />;
  }
  const point = payload[0]?.payload as Point | undefined;
  if (point && point.close != null) {
    return (
      <div className="price-popover">
        <div className="ep-date">{new Date(point.x).toISOString().slice(0, 10)}</div>
        <div className="ep-title">${point.close.toFixed(2)}</div>
      </div>
    );
  }
  return null;
}

function eventDotShape(props: { cx?: number; cy?: number; fill?: string }) {
  return <circle cx={props.cx} cy={props.cy} r={5} fill={props.fill} stroke="#fff" strokeWidth={1.5} />;
}

export function MiniChart({ symbol, events }: MiniChartProps) {
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
            content={<ChartTooltip />}
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
          {eventPoints.some((p) => p.event.kind === "past") && (
            <Scatter
              data={eventPoints.filter((p) => p.event.kind === "past")}
              dataKey="y"
              fill={KIND_COLORS.past}
              shape={eventDotShape}
              isAnimationActive={false}
            />
          )}
          {eventPoints.some((p) => p.event.kind === "predicted") && (
            <Scatter
              data={eventPoints.filter((p) => p.event.kind === "predicted")}
              dataKey="y"
              fill={KIND_COLORS.predicted}
              shape={eventDotShape}
              isAnimationActive={false}
            />
          )}
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}