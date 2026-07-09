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

export function formatPct(frac: number | null | undefined): string {
  if (frac == null) return "—";
  const v = frac * 100;
  return `${v >= 0 ? "+" : ""}${v.toFixed(0)}%`;
}

export function formatScore(s: number | null | undefined): string {
  if (s == null) return "—";
  return s.toFixed(0);
}

export function formatMultiplier(m: number | null | undefined): string {
  if (m == null) return "—";
  return `${m.toFixed(1)}x`;
}

// Strip .US/.LSE suffix from symbols for display
export function displaySymbol(symbol: string): string {
  return symbol.includes(".") ? symbol.slice(0, symbol.lastIndexOf(".")) : symbol;
}

// Get quality badge level based on score
export function getQualityLevel(score: number): "high" | "medium" | "low" {
  if (score >= 70) return "high";
  if (score >= 50) return "medium";
  return "low";
}

// Get quality badge label
export function getQualityLabel(score: number): string {
  if (score >= 70) return "High";
  if (score >= 50) return "Medium";
  return "Low";
}
