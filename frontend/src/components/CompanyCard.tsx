import type { CompanyCard as CompanyCardType } from "../types";
import { displaySymbol, formatPrice, formatMoney, exchangeToFlag } from "../utils";
import { MiniChart } from "./MiniChart";

interface Props {
  company: CompanyCardType;
}

function confidenceBadge(c: "high" | "medium" | "low" | null) {
  if (!c) return null;
  const colors: Record<string, string> = { high: "#1f8a4c", medium: "#b27a00", low: "#bf4f4f" };
  return <span style={{ color: colors[c], fontWeight: 700 }}>{c.toUpperCase()}</span>;
}

function impactText(impact: number | null) {
  if (impact == null) return "Impact: not estimated";
  const multiplier = 1 + impact / 100;
  return `Expected impact: ${impact >= 0 ? "+" : ""}${impact.toFixed(0)}% (×${multiplier.toFixed(1)}; model estimate)`;
}

export function CompanyCard({ company }: Props) {
  const pc = company.past_catalyst;
  const predictedEvents = company.predicted_catalysts;
  const predicted = company.predicted_catalyst;

  return (
    <div className="card company-card-full expanded">
      <div className="card-top">
        <div className="card-chart">
          <MiniChart
            symbol={company.symbol}
            pastEvent={pc ? { start_ts: pc.start_date, end_ts: pc.date } : undefined}
            predictedDates={predictedEvents.map((event) => event.date).filter((date): date is string => Boolean(date))}
          />
        </div>

        <div className="card-info">
          <h3>
            {displaySymbol(company.symbol)} — {company.name} {exchangeToFlag(company.exchange)}
          </h3>
          <div className="card-meta">
            {company.sector !== "Unknown" && company.sector}
            {company.industry !== "Unknown" && ` / ${company.industry}`}
          </div>
          <div className="card-price">
            {formatPrice(company.last_close)} / {formatMoney(company.market_cap_usd)}
          </div>

          {pc && (
            <div className="catalyst-line past">
              <strong>Past catalyst:</strong> {pc.date} | ×{pc.multiplier.toFixed(1)} | {pc.reason}
            </div>
          )}
          {predicted && (
            <div className="catalyst-line predicted">
              <strong>Predicted catalyst:</strong> {predicted.date || "Date unknown"}
              {predicted.event_name && ` | ${predicted.event_name}`}
              {predicted.impact_pct != null && ` | ${impactText(predicted.impact_pct)}`}
              {predicted.confidence && <> | Confidence: {confidenceBadge(predicted.confidence)}</>}
            </div>
          )}
          {!pc && !predicted && (
            <div className="catalyst-line muted">No catalysts detected</div>
          )}

        </div>
      </div>

      <div className="card-detail">
          <h4 className="timeline-title">Catalyst timeline</h4>
          <div className="timeline">
            {predictedEvents.map((event) => (
              <div className="timeline-item predicted" key={event.id}>
                <div className="timeline-marker" />
                <div>
                  <div className="timeline-heading">
                    {event.date || "Date unknown"} — Predicted Catalyst — {event.impact_type || event.event_name || "Other"}
                  </div>
                  {event.event_name && <p><strong>{event.event_name}</strong></p>}
                  <p>{event.summary || "No detailed description available."}</p>
                  <p>{impactText(event.impact_pct)} | Confidence: {confidenceBadge(event.confidence)} | Status: {event.outcome}</p>
                  {event.source_url && (
                    <p><a href={event.source_url} target="_blank" rel="noopener noreferrer" onClick={(e) => e.stopPropagation()}>View source</a></p>
                  )}
                </div>
              </div>
            ))}

            {pc && (
              <div className="timeline-item past">
                <div className="timeline-marker" />
                <div>
                  <div className="timeline-heading">
                    {pc.date} — Past Catalyst — {pc.headline || pc.reason}
                  </div>
                  <p>{pc.summary || "No detailed description available."}</p>
                  {pc.spike_explanation && (
                    <>
                      <h5>Why the spike?</h5>
                      <p>{pc.spike_explanation}</p>
                    </>
                  )}
                  {pc.foreseeable_evidence && (
                    <>
                      <h5>Was it foreseeable?</h5>
                      <span className={`badge ${pc.was_foreseeable ? "yes" : "no"}`}>
                        {pc.was_foreseeable ? "Yes" : "No"}
                      </span>
                      <p>{pc.foreseeable_evidence}</p>
                    </>
                  )}
                </div>
              </div>
            )}

            {!predictedEvents.length && !pc && <p className="muted">No catalyst events recorded.</p>}
          </div>
        </div>
    </div>
  );
}
