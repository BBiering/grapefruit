import type { CompanyCard } from "../types";
import { formatPrice, formatMoney, formatScore, formatMultiplier } from "../utils";
import { StrategyBadge } from "./StrategyBadge";

interface StatsGridProps {
  company: CompanyCard;
}

function Stat({ label, value, accent = false }: { label: string; value: React.ReactNode; accent?: boolean }) {
  return (
    <div className="stat">
      <div className="stat-label">{label}</div>
      <div className={`stat-value ${accent ? "accent" : ""}`}>{value}</div>
    </div>
  );
}

export function StatsGrid({ company }: StatsGridProps) {
  if (company.type === "future") {
    return (
      <div className="stats-grid">
        <Stat label="Current Price" value={formatPrice(company.last_close)} />
        <Stat label="Market Cap" value={formatMoney(company.market_cap_usd)} />
        <Stat label="Quality Score" value={formatScore(company.quality_score)} />
        <Stat label="Combined Score" value={formatScore(company.combined_score)} accent />
        <Stat label="Sector" value={company.sector} />
        <Stat label="Industry" value={company.industry} />
        {company.strategy_tag && (
          <Stat label="Strategy Tag" value={<StrategyBadge tag={company.strategy_tag} />} />
        )}
        {company.upcoming_events && company.upcoming_events.length > 0 && (
          <Stat label="Next Earnings" value={company.upcoming_events[0].event_ts} />
        )}
      </div>
    );
  }

  // Past winner stats
  return (
    <div className="stats-grid">
      <Stat label="Trough Price" value={formatPrice(company.trough_price)} />
      <Stat label="Peak Price" value={formatPrice(company.peak_price)} accent />
      <Stat label="Multiplier" value={formatMultiplier(company.multiplier)} accent />
      <Stat label="Days to Peak" value={company.days_to_peak} />
      <Stat label="Market Cap at Peak" value={formatMoney(company.market_cap_usd)} />
      <Stat label="Sector" value={company.sector} />
      <Stat label="Industry" value={company.industry} />
      {company.was_foreseeable !== undefined && (
        <Stat
          label="Foreseeable?"
          value={
            <span className={`badge ${company.was_foreseeable ? "yes" : "no"}`}>
              {company.was_foreseeable ? "Yes" : "No"}
            </span>
          }
        />
      )}
    </div>
  );
}
