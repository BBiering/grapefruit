import { useMemo, useState } from "react";
import { useCompanies } from "../hooks/useCompanies";
import { CompanyCard } from "../components/CompanyCard";

type SortBy = "past" | "future";

/*
function pct(value: number | null) {
  return value == null ? "—" : `${value >= 0 ? "+" : ""}${value.toFixed(1)}%`;
}
*/

export function Dashboard() {
  const [sortBy, setSortBy] = useState<SortBy>("future");
  // Commented out: sector/industry filters are disabled for now.
  // const [sector, setSector] = useState("all");
  // const [industry, setIndustry] = useState("all");
  const [searchTerm, setSearchTerm] = useState("");

  const { data: companies = [], isLoading } = useCompanies();
  // Commented out: high-level metrics are not displayed at the moment.
  // const { data: performance } = usePredictionPerformance();

  // Commented out: sector/industry option lists retained for future use.
  // const sectors = useMemo(...);
  // const industries = useMemo(...);

  const sorted = useMemo(() => {
    // Commented out: sector/industry filtering disabled.
    const copy = companies;
    if (sortBy === "past") {
      copy.sort((a, b) => (b.past_catalyst?.multiplier ?? 0) - (a.past_catalyst?.multiplier ?? 0));
    } else {
      const order: Record<string, number> = { high: 0, medium: 1, low: 2 };
      copy.sort((a, b) => {
        const oa = a.predicted_catalyst?.confidence ? (order[a.predicted_catalyst.confidence] ?? 3) : 3;
        const ob = b.predicted_catalyst?.confidence ? (order[b.predicted_catalyst.confidence] ?? 3) : 3;
        if (oa !== ob) return oa - ob;
        return (b.predicted_catalyst?.impact_pct ?? 0) - (a.predicted_catalyst?.impact_pct ?? 0);
      });
    }
    return copy;
  }, [companies, sortBy]);

  // Search by company name or ticker.
  const visible = useMemo(() => {
    if (!searchTerm.trim()) return sorted;
    const term = searchTerm.trim().toLowerCase();
    return sorted.filter(
      (company) =>
        company.name.toLowerCase().includes(term) ||
        company.symbol.toLowerCase().includes(term),
    );
  }, [sorted, searchTerm]);

  return (
    <div className="dashboard">
      <header className="topbar glass">
        <div className="topbar-brand">
          <span className="brand-icon">🍊</span>
          <h1 className="brand-name">Grapefruit</h1>
        </div>
      </header>

      {/* Search bar replaced the high-level stats area. */}
      <div className="search-bar">
        <input
          type="search"
          placeholder="Search by company name or ticker…"
          value={searchTerm}
          onChange={(event) => setSearchTerm(event.target.value)}
          aria-label="Search companies"
        />
      </div>

      <main className="card-list">
        {isLoading ? (
          <div className="loading">Loading companies...</div>
        ) : visible.length === 0 ? (
          <div className="loading">No companies match your search</div>
        ) : (
          visible.map((company) => <CompanyCard key={company.symbol} company={company} />)
        )}
      </main>
    </div>
  );
}
