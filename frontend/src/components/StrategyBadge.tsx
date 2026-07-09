interface StrategyBadgeProps {
  tag: "Buy Manually" | "Watchlist" | "Pass";
}

export function StrategyBadge({ tag }: StrategyBadgeProps) {
  const className = tag === "Buy Manually" ? "buy" : tag === "Watchlist" ? "watch" : "pass";

  return <span className={`strategy-badge ${className}`}>{tag}</span>;
}
