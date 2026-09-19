// Formatting utilities shared across components

export function formatMoney(usd: number | null | undefined): string {
  if (usd == null) return "—";
  if (usd >= 1e9) return `$${(usd / 1e9).toFixed(2)}B`;
  if (usd >= 1e6) return `$${(usd / 1e6).toFixed(0)}M`;
  return `$${usd.toFixed(0)}`;
}

export function formatPrice(price: number | null | undefined): string {
  if (price == null) return "—";
  return `$${price.toFixed(2)}`;
}

// Strip exchange suffix from symbols for display
export function displaySymbol(symbol: string): string {
  return symbol.includes(".") ? symbol.slice(0, symbol.lastIndexOf(".")) : symbol;
}

// Map EODHD exchange suffix to country flag
const EXCHANGE_FLAGS: Record<string, string> = {
  US: "🇺🇸",
  PA: "🇫🇷",
  XETRA: "🇩🇪",
  LSE: "🇬🇧",
  HE: "🇫🇮",
  ST: "🇸🇪",
  CO: "🇩🇰",
  SW: "🇨🇭",
  OL: "🇳🇴",
};

export function exchangeToFlag(exchange: string | null | undefined): string {
  if (!exchange) return "";
  return EXCHANGE_FLAGS[exchange] || exchange;
}

// Map EODHD exchange suffix to a country name for filtering.
const EXCHANGE_COUNTRIES: Record<string, string> = {
  US: "United States",
  PA: "France",
  XETRA: "Germany",
  LSE: "United Kingdom",
  HE: "Finland",
  ST: "Sweden",
  CO: "Denmark",
  SW: "Switzerland",
  OL: "Norway",
};

export function exchangeToCountry(exchange: string | null | undefined): string | null {
  if (!exchange) return null;
  return EXCHANGE_COUNTRIES[exchange] || exchange;
}

// Parse a catalyst window string into a display label + optional ISO date.
// Finds ISO dates and quarter/half-year windows anywhere in the text, so an
// undated event whose name embeds one (e.g. "H1 2026 Financial Results")
// still gets a proper date instead of "Date unknown".
const _ISO_RE = /(\d{4})-(\d{2})-(\d{2})/;
const _Q_RE = /\bQ\s*([1-4])['’]?\s*(\d{2}|\d{4})\b/i;
const _H_RE = /\bH([12])\s*['’]?\s*(\d{2}|\d{4})\b/i;
const _MONTH_RE =
  /(?:(\d{1,2})(?:st|nd|rd|th)?[\s,.]*)?(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sept(?:ember)?|sep|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)(?:[\s,.]*(\d{4}))?(?!-?\d)\b/i;
const _MONTH_IDX: Record<string, number> = {
  jan: 1, feb: 2, mar: 3, apr: 4, may: 5, jun: 6,
  jul: 7, aug: 8, sep: 9, sept: 9, oct: 10, nov: 11, dec: 12,
};
const _HALF_TEXT_RE = /\b(?:first|1st|second|2nd)\s+half\s+of\s+(\d{4})\b/i;
const _Q_WORD_RE = /\b(?:first|1st|second|2nd|third|3rd|fourth|4th)\s+quarter(?:\s+of)?\s+(\d{4})\b/i;
const _Q_DIGIT_RE = /\b([1-4])q['’]?(?:\s*of)?\s*(\d{2}|\d{4})\b/i; // "4Q26"
const _LATE_RE =
  /\b(?:late|around|towards? (?:the )?end of|by (?:the )?end of|before (?:the )?end of|year-?end)\s+(?:of\s+)?(20\d{2})\b/i;
const _QIDX: Record<string, number> = {
  first: 1, "1st": 1, second: 2, "2nd": 2, third: 3, "3rd": 3, fourth: 4, "4th": 4,
};

const _year4 = (y: string): string => (y.length === 4 ? y : `${2000 + +y}`);

export function parseWindow(v: string | null | undefined): { label: string; iso: string | null } | null {
  if (!v || !v.trim()) return null;
  const s = v.trim();
  let m = s.match(_ISO_RE);
  if (m) {
    const d = new Date(Date.UTC(+m[1], +m[2] - 1, +m[3]));
    if (!Number.isNaN(d.getTime())) {
      return {
        label: d.toLocaleDateString("en-GB", { year: "numeric", month: "short", day: "numeric" }),
        iso: d.toISOString().slice(0, 10),
      };
    }
  }
  // Explicit windows first: "...in Q4 2026" beats a bare "June" mention.
  m = s.match(_Q_RE);
  if (m) return { label: `Q${m[1]} ${_year4(m[2])}`, iso: null };
  m = s.match(_Q_WORD_RE); // "first quarter of 2027"
  if (m) {
    const q0 = m[0].toLowerCase();
    const q = q0.startsWith("first") || q0.startsWith("1st") ? 1
      : q0.startsWith("second") || q0.startsWith("2nd") ? 2
      : q0.startsWith("third") || q0.startsWith("3rd") ? 3 : 4;
    return { label: `Q${q} ${m[1]}`, iso: null };
  }
  m = s.match(_Q_DIGIT_RE); // "4Q26"
  if (m) return { label: `Q${m[1]} ${_year4(m[2])}`, iso: null };
  m = s.match(_H_RE);
  if (m) return { label: `H${m[1]} ${_year4(m[2])}`, iso: null };
  m = s.match(_HALF_TEXT_RE); // "second half of 2026"
  if (m) return { label: `H${/^s|^2/i.test(m[0]) ? 2 : 1} ${m[1]}`, iso: null };
  m = s.match(_LATE_RE); // "late 2026", "year-end 2026" -> Q4
  if (m) return { label: `Q4 ${m[1]}`, iso: null };
  m = s.match(_MONTH_RE); // "30 Sept 2026" (day), "Sep 2026", "September data cut" (no year)
  if (m) {
    const mo = _MONTH_IDX[m[2].toLowerCase().slice(0, 3)];
    const day = m[1] && +m[1] >= 1 && +m[1] <= 31 ? +m[1] : null;
    const isoLabel = (dt: Date) => ({
      label: dt.toLocaleDateString("en-GB", { year: "numeric", month: "short", day: "numeric" }),
      iso: dt.toISOString().slice(0, 10),
    });
    const quarter = (q: number, y: string) => ({ label: `Q${q} ${y}`, iso: null });
    if (m[3]) {
      if (day) {
        const dt = new Date(Date.UTC(+_year4(m[3]), mo - 1, day));
        if (!Number.isNaN(dt.getTime())) return isoLabel(dt);
      }
      return quarter(Math.floor((mo - 1) / 3) + 1, _year4(m[3]));
    }
    // Month without a year: nearest occurrence at/after today.
    const now = new Date();
    for (const y of [now.getFullYear(), now.getFullYear() + 1]) {
      if (day) {
        const dt = new Date(Date.UTC(y, mo - 1, day));
        if (dt.getTime() >= now.getTime()) return isoLabel(dt);
      } else if (mo === now.getMonth() + 1 && y === now.getFullYear()) {
        return quarter(Math.floor((mo - 1) / 3) + 1, String(y));
      } else if (Date.UTC(y, mo - 1, 1) > now.getTime()) {
        return quarter(Math.floor((mo - 1) / 3) + 1, String(y));
      }
    }
    return null;
  }
  return null;
}

// Humanize a catalyst date/window string. Handles ISO dates ("2026-09-25"),
// quarters ("Q4 2026"), half-years ("H1 2027"), dates embedded in event names,
// and free text. Falls back to "Date unknown" only when there is genuinely
// nothing to show.
export function displayCatalystDate(value: string | null | undefined): string {
  if (!value || !value.trim()) return "Date unknown";
  const p = parseWindow(value);
  return p ? p.label : value.trim();
}

// "Time horizon" label for a predicted catalyst: an exact countdown when the
// date is known, the quarter/half label when only that is known, otherwise
// "Timing TBD".
export function timeHorizon(value: string | null | undefined, from = new Date()): string {
  const p = parseWindow(value);
  if (!p) return "Timing TBD";
  if (p.iso) {
    const target = Date.UTC(
      +p.iso.slice(0, 4),
      +p.iso.slice(5, 7) - 1,
      +p.iso.slice(8, 10),
    );
    const today = Date.UTC(from.getFullYear(), from.getMonth(), from.getDate());
    const days = Math.round((target - today) / 86_400_000);
    if (days < 0) return p.label;
    if (days === 0) return "today";
    if (days === 1) return "tomorrow";
    if (days <= 45) return `in ${days} days`;
    const months = Math.max(1, Math.round(days / 30));
    return `in ~${months} month${months > 1 ? "s" : ""}`;
  }
  return p.label;
}

// Pick the "next binary event" from a deduped predicted list: earliest dated
// event first, then earliest quarter/half, then best confidence, then most
// recently scanned.
const _CONF_RANK: Record<string, number> = { high: 2, medium: 1, low: 0 };

export function pickNextEvent(
  events: {
    date: string | null;
    confidence?: string | null;
    scanned_at?: string;
    event_name?: string | null;
    impact_type?: string | null;
    summary?: string | null;
  }[] | null | undefined,
) {
  if (!events || events.length === 0) return null;
  // Sort key: dated (earliest first) < quarter/half < undated, then
  // best confidence, then recently-scanned first.
  const key = (e: { date: string | null; confidence?: string | null; scanned_at?: string }): number => {
    const p = parseWindow(e.date);
    const t = p?.iso ? Date.parse(p.iso + "T00:00:00Z") : 0; // ~1.75e12 for 2026
    const band = p?.iso ? 0 : p ? 1 : 2;
    const conf = 2 - (_CONF_RANK[e.confidence ?? ""] ?? 0);
    return band * 1e15 + t + conf * 1e8 + (e.scanned_at ? 0 : 1e7);
  };
  return [...events].sort((a, b) => key(a) - key(b))[0] ?? null;
}
