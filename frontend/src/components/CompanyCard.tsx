import { useState } from "react";
import type { CompanyCard as CompanyCardType, ModelNews } from "../types";
import {
  displaySymbol, formatPrice, formatMoney, exchangeToFlag,
  displayCatalystDate, timeHorizon, pickNextEvent,
} from "../utils";
import { MiniChart } from "./MiniChart";
import { WatchlistButton } from "./WatchlistButton";
import { useWatchlist } from "../hooks/useCompanies";

interface Props {
  company: CompanyCardType;
}

const AI_PROVIDERS = [
  { id: "openai", label: "ChatGPT" },
  { id: "anthropic", label: "Claude" },
  { id: "gemini", label: "Gemini" },
] as const;

type AiStatus =
  | { provider: string; label: string; status: "loading" }
  | { provider: string; label: string; status: "error"; message: string }
  | { provider: string; label: string; status: "done"; result: ModelNews };

export function CompanyCard({ company }: Props) {
  const { data: watchlist } = useWatchlist();
  const [ai, setAi] = useState<AiStatus | null>(null);

  const next = pickNextEvent(company.predicted_catalysts);

  async function askAi(provider: string, label: string) {
    setAi({ provider, label, status: "loading" });
    try {
      const res = await fetch("/api/model-news", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          provider,
          symbol: company.symbol,
          name: company.name,
          exchange: company.exchange,
          sector: company.sector,
          context: [
            `Current price: ${formatPrice(company.last_close)}`,
            next
              ? `Next binary event: ${next.event_name || next.impact_type || "catalyst"}${next.date ? ` — ${timeHorizon(next.date)}` : ""}`
              : "No upcoming catalyst detected",
          ].join("\n"),
        }),
      });
      const data = (await res.json()) as ModelNews;
      if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
      setAi({ provider, label, status: "done", result: data });
    } catch (err) {
      setAi({
        provider,
        label,
        status: "error",
        message: err instanceof Error ? err.message : "Request failed",
      });
    }
  }

  return (
    <div className="card company-card-full expanded">
      <div className="card-top">
        <div className="card-chart">
          <MiniChart symbol={company.symbol} events={company.chart_events} />
        </div>

        <div className="card-info">
          <h3 className="card-title-row">
            <span>{displaySymbol(company.symbol)} — {company.name} {exchangeToFlag(company.exchange)}</span>
            <WatchlistButton symbol={company.symbol} isSaved={Boolean(watchlist?.has(company.symbol))} />
          </h3>
          <div className="card-meta">
            {company.sector !== "Unknown" && company.sector}
            {company.industry !== "Unknown" && ` / ${company.industry}`}
          </div>
          <div className="card-price">
            {formatPrice(company.last_close)} / {formatMoney(company.market_cap_usd)}
          </div>

          {next ? (
            <div className="next-event">
              <div className="ne-label">Next binary event</div>
              <div className="ne-type">{next.impact_type || next.event_name || "Catalyst"}</div>
              {next.impact_type && next.event_name && next.event_name !== next.impact_type && (
                <div className="ne-name">{next.event_name}</div>
              )}
              <div className="ne-horizon">Time horizon: {timeHorizon(next.date?.trim() ? next.date : next.event_name)}</div>
            </div>
          ) : company.past_catalyst ? (
            <div className="catalyst-line muted">
              No upcoming binary event. Last move: {displayCatalystDate(company.past_catalyst.date)} ×
              {company.past_catalyst.multiplier.toFixed(1)}
            </div>
          ) : (
            <div className="catalyst-line muted">No catalysts detected</div>
          )}
        </div>
      </div>

      <div className="card-ai">
        <div className="ai-head">
          <h4 className="ai-title">Latest news &amp; pros/cons</h4>
          <div className="ai-buttons">
            {AI_PROVIDERS.map((p) => (
              <button
                key={p.id}
                className="ai-btn"
                disabled={ai?.status === "loading"}
                onClick={() => askAi(p.id, p.label)}
              >
                {p.label}
              </button>
            ))}
          </div>
        </div>

        {ai?.status === "loading" && (
          <div className="ai-result muted">Querying {ai.label} for the latest news…</div>
        )}
        {ai?.status === "error" && (
          <div className="ai-result ai-error">{ai.message}</div>
        )}
        {ai?.status === "done" && ai.result && (
          <div className="ai-result">
            <pre className="ai-text">{ai.result.content}</pre>
          </div>
        )}
      </div>
    </div>
  );
}