import { useRef, useState } from "react";
import type { CompanyCard as CompanyCardType } from "../types";
import { displaySymbol, formatPrice, formatMoney, exchangeToFlag } from "../utils";

interface Props {
  company: CompanyCardType;
  onClose: () => void;
}

interface Message {
  role: "user" | "assistant";
  text: string;
}

function buildContext(company: CompanyCardType): string {
  const pc = company.past_catalyst;
  const lines: string[] = [
    `- Symbol: ${company.symbol}`,
    `- Name: ${company.name}`,
    `- Country: ${exchangeToFlag(company.exchange)} (${company.exchange ?? "unknown"})`,
    `- Sector: ${company.sector}`,
    `- Industry: ${company.industry}`,
    `- Last close: ${formatPrice(company.last_close)}`,
    `- Market cap: ${formatMoney(company.market_cap_usd)}`,
  ];
  if (pc) {
    lines.push(
      `- Past catalyst: ${pc.date}, multiplier x${pc.multiplier.toFixed(1)}, reason "${pc.reason}"`,
      `  window: ${pc.start_date} to ${pc.date}`,
      pc.headline ? `  headline: ${pc.headline}` : "",
      pc.summary ? `  summary: ${pc.summary}` : "",
      pc.spike_explanation ? `  spike: ${pc.spike_explanation}` : "",
    );
  }
  for (const ev of company.predicted_catalysts) {
    lines.push(
      `- Predicted catalyst: ${ev.date ?? "date unknown"}, event "${ev.event_name ?? "unspecified"}", ` +
        `type ${ev.impact_type ?? "other"}, expected impact ${ev.impact_pct != null ? `${ev.impact_pct}%` : "not estimated"}, ` +
        `confidence ${ev.confidence ?? "unknown"}, status ${ev.outcome}`,
      ev.summary ? `  summary: ${ev.summary}` : "",
    );
  }
  return lines.filter((line) => line.trim() !== "").join("\n");
}

export function CompanyChat({ company, onClose }: Props) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const listRef = useRef<HTMLDivElement>(null);
  const context = buildContext(company);

  const send = async () => {
    const question = input.trim();
    if (!question || loading) return;
    setMessages((prev) => [...prev, { role: "user", text: question }]);
    setInput("");
    setLoading(true);
    setError(null);
    try {
      const resp = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ context, question }),
      });
      const data = (await resp.json()) as { answer?: string; error?: string };
      if (!resp.ok || !data.answer) {
        throw new Error(data.error || `Request failed (${resp.status})`);
      }
      setMessages((prev) => [...prev, { role: "assistant", text: data.answer ?? "" }]);
      setTimeout(() => listRef.current?.scrollTo({ top: listRef.current.scrollHeight }), 50);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Chat request failed");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="chat-overlay" onClick={onClose}>
      <div className="chat-window" onClick={(e) => e.stopPropagation()}>
        <div className="chat-header">
          <h4>Ask about {displaySymbol(company.symbol)}</h4>
          <button className="chat-close" onClick={onClose} aria-label="Close chat">
            ×
          </button>
        </div>

        <div className="chat-list" ref={listRef}>
          {messages.length === 0 && (
            <p className="chat-hint">
              Ask anything about this company — the card info (catalysts, prices,
              sectors) is pre-loaded as context. Chemistry with Perplexity: tap
              "I am not financial advice" before trading.
            </p>
          )}
          {messages.map((msg, i) => (
            <div key={i} className={`chat-msg ${msg.role}`}>
              {msg.text}
            </div>
          ))}
          {loading && <div className="chat-msg assistant chat-typing">…</div>}
          {error && <div className="chat-error">{error}</div>}
        </div>

        <div className="chat-input-row">
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && send()}
            placeholder="Ask a question…"
            aria-label="Chat question"
            disabled={loading}
          />
          <button onClick={send} disabled={loading || !input.trim()}>
            Send
          </button>
        </div>
      </div>
    </div>
  );
}
