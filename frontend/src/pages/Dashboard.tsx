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

  // Filter states
  const [selectedSector, setSelectedSector] = useState<string>("all");
  const [selectedIndustry, setSelectedIndustry] = useState<string>("all");
  const [selectedTier, setSelectedTier] = useState<string>("all");

  const { data: companies = [], isLoading } = useCompanies("all");

  // Get unique sectors, industries for filter dropdowns
  const { sectors, industries } = useMemo(() => {
    const sectorSet = new Set<string>();
    const industrySet = new Set<string>();

    companies.forEach(c => {
      if (c.sector && c.sector !== "Unknown") sectorSet.add(c.sector);
      if (c.industry && c.industry !== "Unknown") industrySet.add(c.industry);
    });

    return {
      sectors: Array.from(sectorSet).sort(),
      industries: Array.from(industrySet).sort(),
    };
  }, [companies]);

  // Filter and sort companies
  const filteredAndSortedCompanies = useMemo(() => {
    // Apply filters first (AND logic: all filters must match)
    let filtered = companies.filter(company => {
      // Sector filter
      if (selectedSector !== "all") {
        if (!company.sector || company.sector === "Unknown" || company.sector !== selectedSector) {
          return false;
        }
      }

      // Industry filter
      if (selectedIndustry !== "all") {
        if (!company.industry || company.industry === "Unknown" || company.industry !== selectedIndustry) {
          return false;
        }
      }

      // Catalyst tier filter (by tier_name)
      if (selectedTier !== "all") {
        const catalyst = company.predicted_catalyst || company.forward_catalyst;
        const hasCatalyst = catalyst?.detected;
        const tierName = catalyst?.tier_name;

        if (selectedTier === "no_catalyst" && hasCatalyst) {
          return false;
        }
        if (selectedTier !== "no_catalyst") {
          if (!hasCatalyst || tierName !== selectedTier) {
            return false;
          }
        }
      }

      return true;
    });

    // Then sort
    return filtered.sort((a, b) => {
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
  }, [companies, sortBy, selectedSector, selectedIndustry, selectedTier]);

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

      {/* Sidebar Filters */}
      <aside className="sidebar glass">
        <h3>Filters</h3>
        <p className="filter-description">All filters combine (AND logic)</p>

        <div className="filter-group">
          <label>Sector</label>
          <select value={selectedSector} onChange={(e) => setSelectedSector(e.target.value)}>
            <option value="all">All Sectors</option>
            {sectors.map(sector => (
              <option key={sector} value={sector}>
                {sector}
              </option>
            ))}
          </select>
        </div>

        <div className="filter-group">
          <label>Industry</label>
          <select value={selectedIndustry} onChange={(e) => setSelectedIndustry(e.target.value)}>
            <option value="all">All Industries</option>
            {industries.map(industry => (
              <option key={industry} value={industry}>
                {industry}
              </option>
            ))}
          </select>
        </div>

        <div className="filter-group">
          <label>Catalyst Tier</label>
          <select value={selectedTier} onChange={(e) => setSelectedTier(e.target.value)}>
            <option value="all">All</option>
            <option value="Systemic Volatility">Tier 1: Systemic Volatility (+100-500%)</option>
            <option value="Corporate Acceleration">Tier 2: Corporate Acceleration (+20-50%)</option>
            <option value="Structural Maintenance">Tier 3: Structural Maintenance (Volatile)</option>
            <option value="no_catalyst">No Catalyst</option>
          </select>
        </div>

        <button
          className="reset-filters"
          onClick={() => {
            setSelectedSector("all");
            setSelectedIndustry("all");
            setSelectedTier("all");
          }}
          disabled={selectedSector === "all" && selectedIndustry === "all" && selectedTier === "all"}
        >
          Reset All Filters
        </button>

        <div className="filter-results">
          Showing {filteredAndSortedCompanies.length} of {companies.length} companies
        </div>
      </aside>

      {/* Card Grid */}
      <main className="card-grid">
        {isLoading ? (
          <div className="loading">Loading companies...</div>
        ) : filteredAndSortedCompanies.length === 0 ? (
          <div className="loading">No companies match your filters</div>
        ) : (
          filteredAndSortedCompanies.map((company, index) => (
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
            const nextIndex = (selectedIndex + 1) % filteredAndSortedCompanies.length;
            setSelectedCompany(filteredAndSortedCompanies[nextIndex]);
            setSelectedIndex(nextIndex);
          }}
          onPrev={() => {
            const prevIndex = (selectedIndex - 1 + filteredAndSortedCompanies.length) % filteredAndSortedCompanies.length;
            setSelectedCompany(filteredAndSortedCompanies[prevIndex]);
            setSelectedIndex(prevIndex);
          }}
        />
      )}
    </div>
  );
}
