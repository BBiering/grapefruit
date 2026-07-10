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
  const [selectedIndustry, setSelectedIndustry] = useState<string>("all");
  const [selectedImpactType, setSelectedImpactType] = useState<string>("all");

  const { data: companies = [], isLoading } = useCompanies("all");

  // Debug: Check for duplicates and missing data
  console.log(`[Dashboard] Total companies: ${companies.length}`);
  const symbolCounts = new Map<string, number>();
  companies.forEach(c => symbolCounts.set(c.symbol, (symbolCounts.get(c.symbol) || 0) + 1));
  const duplicates = Array.from(symbolCounts.entries()).filter(([_, count]) => count > 1);
  if (duplicates.length > 0) {
    console.warn(`[Dashboard] Found ${duplicates.length} duplicate symbols:`, duplicates);
  }
  const missingData = companies.filter(c => !c.name || c.name === c.symbol || c.sector === "Unknown");
  if (missingData.length > 0) {
    console.warn(`[Dashboard] Found ${missingData.length} companies with missing data:`,
      missingData.slice(0, 5).map(c => ({ symbol: c.symbol, name: c.name, sector: c.sector, industry: c.industry }))
    );
  }

  // Get unique industries and impact types for filter dropdowns
  const { industries, impactTypes } = useMemo(() => {
    const industrySet = new Set<string>();
    const impactTypeSet = new Set<string>();

    companies.forEach(c => {
      if (c.industry && c.industry !== "Unknown") industrySet.add(c.industry);

      const catalyst = c.predicted_catalyst || c.forward_catalyst;
      if (catalyst?.detected && catalyst?.impact_type) {
        impactTypeSet.add(catalyst.impact_type);
      }
    });

    return {
      industries: Array.from(industrySet).sort(),
      impactTypes: Array.from(impactTypeSet).sort(),
    };
  }, [companies]);

  // Filter and sort companies
  const filteredAndSortedCompanies = useMemo(() => {
    // Apply filters first (AND logic: all filters must match)
    let filtered = companies.filter(company => {
      // Industry filter
      if (selectedIndustry !== "all") {
        if (!company.industry || company.industry === "Unknown" || company.industry !== selectedIndustry) {
          return false;
        }
      }

      // Catalyst impact type filter (Tier 1 events only - Binary FDA, etc.)
      if (selectedImpactType !== "all") {
        const catalyst = company.predicted_catalyst || company.forward_catalyst;
        const hasCatalyst = catalyst?.detected;
        const impactType = catalyst?.impact_type;

        if (selectedImpactType === "no_catalyst" && hasCatalyst) {
          return false;
        }
        if (selectedImpactType !== "no_catalyst") {
          if (!hasCatalyst || impactType !== selectedImpactType) {
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
  }, [companies, sortBy, selectedIndustry, selectedImpactType]);

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
          <label>Catalyst Event Type</label>
          <select value={selectedImpactType} onChange={(e) => setSelectedImpactType(e.target.value)}>
            <option value="all">All</option>
            {impactTypes.map(type => (
              <option key={type} value={type}>
                {type}
              </option>
            ))}
            <option value="no_catalyst">No Catalyst</option>
          </select>
        </div>

        <button
          className="reset-filters"
          onClick={() => {
            setSelectedIndustry("all");
            setSelectedImpactType("all");
          }}
          disabled={selectedIndustry === "all" && selectedImpactType === "all"}
        >
          Reset Filters
        </button>
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
