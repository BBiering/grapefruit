import { useState } from "react";
import { createPortal } from "react-dom";
import type { CompanyCard as CompanyCardType } from "../types";
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

type NewsState =
  | { status: "idle" }
  | { status: "loading" }
  | { status: "error"; error: string }
  | { status: "done"; content: string; model?: string };

// Minimal markdown-ish rendering for the Gemini profile: numbered/## lines
// become section headings, bullets stay bullets, everything else is prose.
function formattedSections(text: string) {
  return text.split("\n").map((raw, i) => {
    const t = raw.trim();
    if (!t) return null;
    if (/^\d+\./.test(t) || /^#{1,3}\s/.test(t)) {
      return (
        <h5 className="pf-h" key={i}>
          {t.replace(/^#+\s*/, "").replace(/\*\*/g, "")}
        </h5>
      );
    }
    if (/^[-•·*]\s/.test(t)) {
      return (
        <div className="pf-li" key={i}>
          {t.replace(/^[-•·*]\s*/, "• ").replace(/\*\*/g, "")}
        </div>
      );
    }
    return (
      <p className="pf-p" key={i}>
        {t.replace(/\*\*/g, "")}
      </p>
    );
  });
}

export function CompanyCard({ company }: Props) {
  const { data: watchlist } = useWatchlist();
  const [news, setNews] = useState<NewsState>({ status: "idle" });

  const next = pickNextEvent(company.predicted_catalysts);

  async function askNews() {
    setNews({ status: "loading" });
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), 70_000);
    try {
      const res = await fetch("/api/gemini-profile", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        signal: ctrl.signal,
        body: JSON.stringify({
          symbol: company.symbol,
          name: company.name,
          exchange: company.exchange,
          sector: company.sector,
          context: [
            `Last close: ${formatPrice(company.last_close)}`,
            `Market cap: ${formatMoney(company.market_cap_usd)}`,
            next
              ? `Next binary event: ${next.event_name || next.impact_type || "catalyst"}${next.date ? ` (${timeHorizon(next.date)})` : ""}`
              : "No upcoming catalyst detected",
          ].join("\n"),
        }),
      });
      const data = (await res.json()) as { content?: string; error?: string };
      if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
      setNews({ status: "done", content: data.content || "" });
    } catch (err) {
      setNews({
        status: "error",
        error:
          err instanceof DOMException && err.name === "AbortError"
            ? "The request timed out after 70s. The model may be slow; try again."
            : err instanceof Error
              ? err.message
              : "Request failed",
      });
    } finally {
      clearTimeout(timer);
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
              <div className="ne-horizon">
                Time horizon: {timeHorizon(next.date?.trim() ? next.date : next.event_name)}
              </div>
            </div>
          ) : company.past_catalyst ? (
            <div className="catalyst-line muted">
              No upcoming binary event. Last move: {displayCatalystDate(company.past_catalyst.date)} ×
              {company.past_catalyst.multiplier.toFixed(1)}
            </div>
          ) : (
            <div className="catalyst-line muted">No catalysts detected</div>
          )}

          <button className="news-btn" onClick={askNews} disabled={news.status === "loading"}>
            🗞️ News
          </button>
        </div>
      </div>

      {news.status !== "idle" &&
        createPortal(
          <div className="news-overlay" onClick={() => setNews({ status: "idle" })}>
            <div className="news-modal" onClick={(e) => e.stopPropagation()}>
              <div className="news-modal-head">
                <h4 className="news-modal-title">Grapefruit · {displaySymbol(company.symbol)} — Gemini profile</h4>
                <button className="news-close" onClick={() => setNews({ status: "idle" })} aria-label="Close">
                  ✕
                </button>
              </div>
              <div className="news-modal-body">
                {news.status === "loading" && <div className="muted">Gemini is researching {company.name}…</div>}
                {news.status === "error" && <div className="ai-error">{news.error}</div>}
                {news.status === "done" && news.content && formattedSections(news.content)}
              </div>
            </div>
          </div>,
          document.body,
        )}
    </div>
  );
}