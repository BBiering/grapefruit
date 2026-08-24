import { useMemo, useState } from "react";
import { useCompanies } from "../hooks/useCompanies";
import { CompanyCard } from "../components/CompanyCard";
import { exchangeToCountry, exchangeToFlag } from "../utils";

type SortBy = "past" | "future";
type CatalystFilter = "all" | "past" | "predicted" | "both";

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
  const [catalystFilter, setCatalystFilter] = useState<CatalystFilter>("all");

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
      // Predicted-first sort: biggest expected impact first; companies with
      // no predicted catalyst sink to the bottom.
      copy.sort((a, b) => {
        const ia = a.predicted_catalyst?.impact_pct ?? -Infinity;
        const ib = b.predicted_catalyst?.impact_pct ?? -Infinity;
        return ib - ia;
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

  // Catalyst-type filter (all / past / predicted / both).
  const catalystFiltered = useMemo(() => {
    if (catalystFilter === "all") return sorted;
    return sorted.filter((company) => {
      const hasPast = Boolean(company.past_catalyst);
      const hasPredicted = company.predicted_catalysts.length > 0;
      if (catalystFilter === "past") return hasPast;
      if (catalystFilter === "predicted") return hasPredicted;
      return hasPast || hasPredicted; // "both"
    });
  }, [sorted, catalystFilter]);

  // Search by company name or ticker, plus country filter.
  const visible = useMemo(() => {
    let result = catalystFiltered.filter((company) => {
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
  }, [catalystFiltered, searchTerm, country]);

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
        <select
          value={catalystFilter}
          onChange={(event) => setCatalystFilter(event.target.value as CatalystFilter)}
          aria-label="Filter by catalyst"
        >
          <option value="all">All catalysts</option>
          <option value="predicted">Predicted catalysts</option>
          <option value="past">Past catalysts</option>
          <option value="both">Both</option>
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
