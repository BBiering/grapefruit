import { useMemo, useState } from "react";
import { useCompanies } from "../hooks/useCompanies";
import { CompanyCard } from "../components/CompanyCard";

type SortBy = "past" | "future";

export function Dashboard() {
  const [sortBy, setSortBy] = useState<SortBy>("future");

  const { data: companies = [], isLoading } = useCompanies();

  const sorted = useMemo(() => {
    const copy = [...companies];
    if (sortBy === "past") {
      // Sort by past catalyst multiplier (strongest first), then companies without past at end
      copy.sort((a, b) => {
        const ma = a.past_catalyst?.multiplier ?? 0;
        const mb = b.past_catalyst?.multiplier ?? 0;
        return mb - ma;
      });
    } else {
      // Sort by future catalyst confidence (high > medium > low > none),
      // then by expected impact percentage (largest first)
      const order: Record<string, number> = { high: 0, medium: 1, low: 2 };
      copy.sort((a, b) => {
        const ca = a.future_catalyst?.confidence;
        const cb = b.future_catalyst?.confidence;
        const oa = ca ? (order[ca] ?? 3) : 3;
        const ob = cb ? (order[cb] ?? 3) : 3;
        if (oa !== ob) return oa - ob;
        return (b.future_catalyst?.impact_pct ?? 0) - (a.future_catalyst?.impact_pct ?? 0);
      });
    }
    return copy;
  }, [companies, sortBy]);

  return (
    <div className="dashboard">
      <header className="topbar glass">
        <div className="topbar-brand">
          <span className="brand-icon">🍊</span>
          <h1 className="brand-name">Grapefruit</h1>
        </div>
        <div style={{ flex: 1 }} />
        <select value={sortBy} onChange={(e) => setSortBy(e.target.value as SortBy)}>
          <option value="future">Sort: Future Catalysts (confidence)</option>
          <option value="past">Sort: Past Catalysts (multiplier)</option>
        </select>
      </header>

      <main className="card-list">
        {isLoading ? (
          <div className="loading">Loading companies...</div>
        ) : sorted.length === 0 ? (
          <div className="loading">No companies found</div>
        ) : (
          sorted.map((company) => (
            <CompanyCard key={company.symbol} company={company} />
          ))
        )}
      </main>
    </div>
  );
}
