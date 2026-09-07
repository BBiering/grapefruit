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

// Humanize a catalyst date/window string. Handles ISO dates ("2026-09-25"),
// quarters ("Q4 2026"), half-years ("H1 2027"), and free text. Falls back to
// "Date unknown" only when there is genuinely nothing to show.
export function displayCatalystDate(value: string | null | undefined): string {
  if (!value || !value.trim()) return "Date unknown";
  const v = value.trim();
  let m = v.match(/^Q\s*([1-4])\s*(\d{4})$/i);       // "Q4 2026", "Q42026"
  if (m) return `Q${m[1]} ${m[2]}`;
  m = v.match(/^4Q\s*([1-4])\s*(\d{4})$/i);          // "4Q 2026"
  if (m) return `Q${m[1]} ${m[2]}`;
  m = v.match(/^H([12])\s*(\d{4})$/i);                // "H1 2027"
  if (m) return `H${m[1]} ${m[2]}`;
  m = v.match(/^(\d{4})-(\d{2})-(\d{2})$/);          // "2026-09-25"
  if (m) {
    const d = new Date(Date.UTC(+m[1], +m[2] - 1, +m[3]));
    if (!Number.isNaN(d.getTime())) {
      return d.toLocaleDateString("en-GB", { year: "numeric", month: "short", day: "numeric" });
    }
  }
  return v; // already human-readable ("Q4 2026", "H1 2027", free text)
}
