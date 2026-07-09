import { useMemo, useState } from "react";
import { useCompanies } from "../hooks/useCompanies";
import { CompanyCard } from "../components/CompanyCard";
import { CompanyModal } from "../components/CompanyModal";
import type { CompanyCard as CompanyCardType } from "../types";

type Filter = "all" | "future" | "past";
type SortBy = "score" | "price" | "marketcap";

export function Dashboard() {
  const [sortBy, setSortBy] = useState<SortBy>("score");
  const [selectedCompany, setSelectedCompany] = useState<CompanyCardType | null>(null);
  const [selectedIndex, setSelectedIndex] = useState<number>(0);

  const { data: companies = [], isLoading } = useCompanies("all");

  const sortedCompanies = useMemo(() => {
    return [...companies].sort((a, b) => {
      switch (sortBy) {
        case "score":
          // Sort by: 1) Tier (lower = higher priority), 2) Event date (soonest), 3) Quality (highest)
          // Get tier from forward_catalyst or use 999 for no catalyst
          const tierA = a.forward_catalyst?.detected ? 1 : 999; // Simplified tier logic
          const tierB = b.forward_catalyst?.detected ? 1 : 999;

          if (tierA !== tierB) return tierA - tierB;

          // If same tier, sort by event date (soonest first)
          const dateA = a.upcoming_events?.[0]?.event_ts || "9999-12-31";
          const dateB = b.upcoming_events?.[0]?.event_ts || "9999-12-31";

          if (dateA !== dateB) return dateA.localeCompare(dateB);

          // If same date, sort by quality (highest first)
          return b.quality_score - a.quality_score;

        case "price":
          return b.last_close - a.last_close;
        case "marketcap":
          return (b.market_cap_usd || 0) - (a.market_cap_usd || 0);
        default:
          return 0;
      }
    });
  }, [companies, sortBy]);

  return (
    <div className="dashboard">
      {/* Topbar */}
      <header className="topbar glass">
        <div className="topbar-brand">
          <span className="brand-icon">🍊</span>
          <h1 className="brand-name">Grapefruit</h1>
        </div>

        <div style={{ flex: 1 }} />

        <select value={sortBy} onChange={(e) => setSortBy(e.target.value as SortBy)}>
          <option value="score">Sort: Priority (Catalyst + Quality)</option>
          <option value="price">Sort: Price</option>
          <option value="marketcap">Sort: Market Cap</option>
        </select>
      </header>

      {/* Card Grid */}
      <main className="card-grid">
        {isLoading ? (
          <div className="loading">Loading companies...</div>
        ) : sortedCompanies.length === 0 ? (
          <div className="loading">No companies found</div>
        ) : (
          sortedCompanies.map((company, index) => (
            <CompanyCard
              key={company.symbol}
              company={company}
              onClick={() => {
                setSelectedCompany(company);
                setSelectedIndex(index);
              }}
            />
          ))
        )}
      </main>

      {/* Modal */}
      {selectedCompany && (
        <CompanyModal
          company={selectedCompany}
          onClose={() => setSelectedCompany(null)}
          onNext={() => {
            const nextIndex = (selectedIndex + 1) % sortedCompanies.length;
            setSelectedCompany(sortedCompanies[nextIndex]);
            setSelectedIndex(nextIndex);
          }}
          onPrev={() => {
            const prevIndex = (selectedIndex - 1 + sortedCompanies.length) % sortedCompanies.length;
            setSelectedCompany(sortedCompanies[prevIndex]);
            setSelectedIndex(prevIndex);
          }}
        />
      )}
    </div>
  );
}
