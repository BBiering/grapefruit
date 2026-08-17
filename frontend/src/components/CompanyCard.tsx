import { useState } from "react";
import type { CompanyCard as CompanyCardType } from "../types";
import { displaySymbol, formatPrice, formatMoney, exchangeToFlag } from "../utils";
import { MiniChart } from "./MiniChart";

interface Props {
  company: CompanyCardType;
}

function confidenceBadge(c: "high" | "medium" | "low" | null) {
  if (!c) return null;
  const colors: Record<string, string> = { high: "#1f8a4c", medium: "#f4bd4c", low: "#bf4f4f" };
  return (
    <span style={{ color: colors[c] || "#6b6661", fontWeight: 600, fontSize: "0.8rem" }}>
      {c.toUpperCase()}
    </span>
  );
}

export function CompanyCard({ company }: Props) {
  const [expanded, setExpanded] = useState(false);

  const pc = company.past_catalyst;
  const fc = company.future_catalyst;

  return (
    <div
      className={`card company-card-full ${expanded ? "expanded" : ""}`}
      onClick={() => setExpanded(!expanded)}
    >
      {/* Top row: chart + key info */}
      <div className="card-top">
        <div className="card-chart">
          <MiniChart
            symbol={company.symbol}
            pastEvent={pc ? { start_ts: pc.date, multiplier: pc.multiplier } : undefined}
            futureDate={fc?.date || undefined}
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

          {/* Inline catalysts */}
          {pc && (
            <div className="catalyst-line past">
              <strong>Past:</strong> {pc.date} | ×{pc.multiplier.toFixed(1)} | {pc.reason}
            </div>
          )}
          {fc && (
            <div className="catalyst-line future">
              <strong>Future:</strong> {fc.date || "TBD"}
              {fc.impact_pct != null && ` | ×${(1 + fc.impact_pct / 100).toFixed(1)}?`}
              {fc.event_name && ` | ${fc.event_name}`}
              {" | "}Confidence: {confidenceBadge(fc.confidence)}
            </div>
          )}
          {!pc && !fc && (
            <div className="catalyst-line muted">No catalysts detected</div>
          )}

          <div className="expand-hint">{expanded ? "▲ collapse" : "▼ expand"}</div>
        </div>
      </div>

      {/* Expanded detail section */}
      {expanded && (
        <div className="card-detail">
          {pc && (pc.spike_explanation || pc.summary) && (
            <div className="detail-block">
              <h4>Past Catalyst — {pc.date} (×{pc.multiplier.toFixed(1)})</h4>
              {pc.headline && <p><strong>{pc.headline}</strong></p>}
              {pc.summary && <p>{pc.summary}</p>}
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
          )}

          {fc && fc.summary && (
            <div className="detail-block">
              <h4>Future Catalyst — {fc.date || "TBD"}</h4>
              <p>{fc.summary}</p>
              {fc.source_url && (
                <p><a href={fc.source_url} target="_blank" rel="noopener noreferrer">View source</a></p>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
