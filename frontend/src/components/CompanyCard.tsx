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
  | { status: "streaming"; text: string }
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
    const timer = setTimeout(() => ctrl.abort(), 75_000);
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

      // The profile streams as NDJSON deltas: {"d":"<text>"}
      if (!res.ok || !res.body) {
        const raw = await res.text().catch(() => "");
        let data: { error?: string } = {};
        try { data = JSON.parse(raw); } catch { /* non-JSON body */ }
        throw new Error(data.error || raw.trim().slice(0, 300) || `HTTP ${res.status}`);
      }

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buf = "";
      let text = "";
      let error = "";
      setNews({ status: "streaming", text: "" });
      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        buf += decoder.decode(value, { stream: true });
        const lines = buf.split("\n");
        buf = lines.pop() ?? "";
        for (const line of lines) {
          if (!line.trim()) continue;
          let row: { d?: string; error?: string };
          try { row = JSON.parse(line); } catch { continue; }
          if (row.d) {
            text += row.d;
            setNews({ status: "streaming", text });
          }
          if (row.error) error = row.error;
        }
      }
      if (error) throw new Error(error);
      if (!text.trim()) throw new Error("model returned an empty answer");
      setNews({ status: "done", content: text });
    } catch (err) {
      setNews((prev) => {
        // Keep whatever streamed in if we were interrupted mid-profile.
        if (prev.status === "streaming" && prev.text.trim()) {
          const note = `\n\n[generation stopped: ${err instanceof Error ? err.message : "error"}]`;
          return { status: "done", content: prev.text + note };
        }
        return {
          status: "error",
          error:
            err instanceof DOMException && err.name === "AbortError"
              ? "The request timed out after 75s. Try again."
              : err instanceof Error ? err.message : "Request failed",
        };
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
                <span className="ne-horizon-label">Time horizon:</span>
                <span className="ne-pill">
                  {timeHorizon(next.date?.trim() ? next.date : (next.event_name || next.summary))}
                </span>
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

          <button className="news-btn" onClick={askNews} disabled={news.status === "loading" || news.status === "streaming"}>
            🗞️ News
          </button>
        </div>
      </div>

      {news.status !== "idle" &&
        createPortal(
          <div className="news-overlay" onClick={() => setNews({ status: "idle" })}>
            <div className="news-modal" onClick={(e) => e.stopPropagation()}>
              <div className="news-modal-head">
                <h4 className="news-modal-title">Latest News about {company.name} - Powered by Gemini</h4>
                <button className="news-close" onClick={() => setNews({ status: "idle" })} aria-label="Close">
                  ✕
                </button>
              </div>
              <div className="news-modal-body">
                {news.status === "loading" && <div className="muted">Gemini is researching {company.name}…</div>}
                {news.status === "streaming" && (
                  <>
                    {formattedSections(news.text)}
                    <div className="muted pf-stream">generating…</div>
                  </>
                )}
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