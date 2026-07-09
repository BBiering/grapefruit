import type { CompanyCard as CompanyCardType } from "../types";
import { displaySymbol, formatPrice, formatMoney } from "../utils";
import { QualityBadge } from "./QualityBadge";
import { StrategyBadge } from "./StrategyBadge";
import { MiniChart } from "./MiniChart";

interface CompanyCardProps {
  company: CompanyCardType;
  onClick: () => void;
}

export function CompanyCard({ company, onClick }: CompanyCardProps) {
  return (
    <div className="card company-card" onClick={onClick}>
      {/* Header: Symbol + Name */}
      <div className="card-header">
        <h3>{displaySymbol(company.symbol)}</h3>
        <p className="muted">{company.name}</p>
      </div>

      {/* Metadata: Sector / Industry */}
      <div className="card-meta">
        {company.sector} / {company.industry}
      </div>

      {/* Price + Market Cap */}
      <div className="card-price">
        {formatPrice(company.last_close)} / {formatMoney(company.market_cap_usd)}
      </div>

      {/* Quality Score + Badge */}
      <QualityBadge score={company.quality_score} />

      {/* Strategy Badge (future only) */}
      {company.type === "future" && company.strategy_tag && (
        <div className="card-strategy">
          <StrategyBadge tag={company.strategy_tag} />
        </div>
      )}

      {/* Mini Chart */}
      <MiniChart
        symbol={company.symbol}
        recentMove={company.recent_move}
        winnerEvent={company.winner_event}
        catalyst={company.forward_catalyst}
      />

      {/* Type Badge */}
      <div className="card-type">
        {company.type === "future" ? "🚀 Potential" : "🏆 Historical"}
      </div>
    </div>
  );
}
