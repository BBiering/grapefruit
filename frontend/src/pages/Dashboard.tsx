import { useMemo, useState } from "react";
import { useCompanies, usePredictionPerformance } from "../hooks/useCompanies";
import { CompanyCard } from "../components/CompanyCard";

type SortBy = "past" | "future";

function pct(value: number | null) {
  return value == null ? "—" : `${value >= 0 ? "+" : ""}${value.toFixed(1)}%`;
}

export function Dashboard() {
  const [sortBy, setSortBy] = useState<SortBy>("future");
  const [sector, setSector] = useState("all");
  const [industry, setIndustry] = useState("all");

  const { data: companies = [], isLoading } = useCompanies();
  const { data: performance } = usePredictionPerformance();

  const sectors = useMemo(
    () => [...new Set(companies.map((company) => company.sector).filter((value) => value !== "Unknown"))].sort(),
    [companies],
  );
  const industries = useMemo(
    () => [...new Set(companies.map((company) => company.industry).filter((value) => value !== "Unknown"))].sort(),
    [companies],
  );

  const sorted = useMemo(() => {
    const copy = companies.filter((company) =>
      (sector === "all" || company.sector === sector) &&
      (industry === "all" || company.industry === industry),
    );
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
  }, [companies, sortBy, sector, industry]);

  return (
    <div className="dashboard">
      <header className="topbar glass">
        <div className="topbar-brand">
          <span className="brand-icon">🍊</span>
          <h1 className="brand-name">Grapefruit</h1>
        </div>
        <div className="dashboard-controls">
          <select value={sector} onChange={(e) => setSector(e.target.value)} aria-label="Filter by sector">
            <option value="all">All sectors</option>
            {sectors.map((value) => <option key={value}>{value}</option>)}
          </select>
          <select value={industry} onChange={(e) => setIndustry(e.target.value)} aria-label="Filter by industry">
            <option value="all">All industries</option>
            {industries.map((value) => <option key={value}>{value}</option>)}
          </select>
          <select value={sortBy} onChange={(e) => setSortBy(e.target.value as SortBy)} aria-label="Sort companies">
            <option value="future">Sort: Predicted catalysts</option>
            <option value="past">Sort: Past catalysts</option>
          </select>
        </div>
      </header>

      {performance && (
        <section className="performance-panel" aria-label="Prediction performance">
          <div><strong>{performance.total}</strong><span>predictions</span></div>
          <div><strong>{performance.pending}</strong><span>pending review</span></div>
          <div><strong>{performance.occurred}</strong><span>occurred</span></div>
          <div><strong>{performance.missed}</strong><span>missed</span></div>
          <div><strong>{performance.hit_rate == null ? "—" : `${(performance.hit_rate * 100).toFixed(0)}%`}</strong><span>hit rate</span></div>
          <div><strong>{pct(performance.average_actual_pct)}</strong><span>avg actual move</span></div>
          <div><strong>{pct(performance.average_expected_pct)}</strong><span>avg expected move</span></div>
        </section>
      )}

      <main className="card-list">
        {isLoading ? (
          <div className="loading">Loading companies...</div>
        ) : sorted.length === 0 ? (
          <div className="loading">No companies match these filters</div>
        ) : (
          sorted.map((company) => <CompanyCard key={company.symbol} company={company} />)
        )}
      </main>
    </div>
  );
}
