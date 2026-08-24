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
