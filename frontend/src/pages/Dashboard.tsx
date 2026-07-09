import { useMemo, useState } from "react";
import { useCompanies } from "../hooks/useCompanies";
import { CompanyCard } from "../components/CompanyCard";
import { CompanyModal } from "../components/CompanyModal";
import type { CompanyCard as CompanyCardType } from "../types";

type Filter = "all" | "future" | "past";
type SortBy = "score" | "price" | "marketcap";

export function Dashboard() {
  const [filter, setFilter] = useState<Filter>("all");
  const [sortBy, setSortBy] = useState<SortBy>("score");
  const [selectedCompany, setSelectedCompany] = useState<CompanyCardType | null>(null);

  const { data: companies = [], isLoading } = useCompanies(filter);

  const sortedCompanies = useMemo(() => {
    return [...companies].sort((a, b) => {
      switch (sortBy) {
        case "score":
          // Sort by combined_score (future) or multiplier (past), highest first
          return (b.combined_score || b.multiplier || 0) - (a.combined_score || a.multiplier || 0);
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

        <div className="topbar-filters">
          <button className={filter === "all" ? "active" : ""} onClick={() => setFilter("all")}>
            All Companies
          </button>
          <button className={filter === "future" ? "active" : ""} onClick={() => setFilter("future")}>
            🚀 Future
          </button>
          <button className={filter === "past" ? "active" : ""} onClick={() => setFilter("past")}>
            🏆 Past
          </button>
        </div>

        <select value={sortBy} onChange={(e) => setSortBy(e.target.value as SortBy)}>
          <option value="score">Sort: Score</option>
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
          sortedCompanies.map((company) => (
            <CompanyCard key={company.symbol} company={company} onClick={() => setSelectedCompany(company)} />
          ))
        )}
      </main>

      {/* Modal */}
      {selectedCompany && <CompanyModal company={selectedCompany} onClose={() => setSelectedCompany(null)} />}
    </div>
  );
}
