import { useMemo, useState } from "react";
import { useCompanies } from "../hooks/useCompanies";
import { CompanyCard } from "../components/CompanyCard";
import { exchangeToCountry, exchangeToFlag } from "../utils";

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
  const [country, setCountry] = useState("all");

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

  // Distinct countries present in the data (from the exchange field), each
  // paired with the flag of one of its exchanges for display.
  const countries = useMemo(() => {
    const byCountry = new Map<string, string>(); // country -> flag
    for (const c of companies) {
      const countryName = exchangeToCountry(c.exchange);
      if (!countryName) continue;
      if (!byCountry.has(countryName)) byCountry.set(countryName, exchangeToFlag(c.exchange));
    }
    return [...byCountry.entries()]
      .map(([name, flag]) => ({ name, flag }))
      .sort((a, b) => a.name.localeCompare(b.name));
  }, [companies]);

  // Search by company name or ticker, plus country filter.
  const visible = useMemo(() => {
    let result = sorted.filter((company) => {
      if (country !== "all" && exchangeToCountry(company.exchange) !== country) return false;
      return true;
    });
    if (searchTerm.trim()) {
      const term = searchTerm.trim().toLowerCase();
      result = result.filter(
        (company) =>
          company.name.toLowerCase().includes(term) ||
          company.symbol.toLowerCase().includes(term),
      );
    }
    return result;
  }, [sorted, searchTerm, country]);

  return (
    <div className="dashboard">
      <header className="topbar glass">
        <div className="topbar-brand">
          <span className="brand-icon">🍊</span>
          <h1 className="brand-name">Grapefruit</h1>
        </div>
      </header>

      {/* Search + country filter (replaced the high-level stats area). */}
      <div className="search-bar">
        <input
          type="search"
          placeholder="Search by company name or ticker…"
          value={searchTerm}
          onChange={(event) => setSearchTerm(event.target.value)}
          aria-label="Search companies"
        />
        <select
          value={country}
          onChange={(event) => setCountry(event.target.value)}
          aria-label="Filter by country"
        >
          <option value="all">🌍 All countries</option>
          {countries.map(({ name, flag }) => (
            <option key={name} value={name}>{flag} {name}</option>
          ))}
        </select>
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
