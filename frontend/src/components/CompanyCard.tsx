import type { CompanyCard as CompanyCardType } from "../types";
import { displaySymbol, formatPrice, formatMoney, exchangeToFlag } from "../utils";
import { StrategyBadge } from "./StrategyBadge";
import { MiniChart } from "./MiniChart";

interface CompanyCardProps {
  company: CompanyCardType;
  onClick: () => void;
}

export function CompanyCard({ company, onClick }: CompanyCardProps) {
  return (
    <div className="card company-card" onClick={onClick}>
      {/* Header: Symbol - Name - Flag */}
      <div className="card-header">
        <h3>{displaySymbol(company.symbol)} — {company.name} {exchangeToFlag(company.exchange)}</h3>
      </div>

      {/* Metadata: Sector / Industry */}
      {company.sector && company.sector !== "Unknown" && (
        <div className="card-meta">
          {company.sector}
          {company.industry && company.industry !== "Unknown" && ` / ${company.industry}`}
        </div>
      )}

      {/* Price + Market Cap */}
      <div className="card-price">
        {formatPrice(company.last_close)} / {formatMoney(company.market_cap_usd)}
      </div>

      {/* Strategy Badge */}
      {company.strategy_tag && (
        <div className="card-strategy">
          <StrategyBadge tag={company.strategy_tag} />
        </div>
      )}

      {/* Mini Chart */}
      <MiniChart
        symbol={company.symbol}
        catalyst={company.predicted_catalyst}
      />
    </div>
  );
}
