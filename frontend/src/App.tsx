import { useState } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import PastWinners from "./pages/PastWinners";
import FutureWinners from "./pages/FutureWinners";
import { hasSupabaseConfig } from "./supabase";

const qc = new QueryClient({
  defaultOptions: { queries: { retry: 1, staleTime: 60_000 } },
});

type Tab = "past" | "future";

export default function App() {
  const [tab, setTab] = useState<Tab>("past");

  return (
    <QueryClientProvider client={qc}>
      <div className="app">
        <h1>🍊 Grapefruit</h1>
        <div className="banner">
          <strong>Survivorship bias:</strong> the US symbol list is dominated by
          currently active tickers. Delisted, acquired, and bankrupt stocks are
          largely absent. Treat every winner as filtered through survivorship.
        </div>

        {!hasSupabaseConfig && (
          <div className="card" style={{ background: "#3a1f1f" }}>
            <strong>Supabase env vars missing.</strong>{" "}
            Set <code>VITE_SUPABASE_URL</code> and <code>VITE_SUPABASE_ANON_KEY</code> in
            Vercel project settings, then redeploy.
          </div>
        )}

        <nav>
          <button
            className={tab === "past" ? "tab active" : "tab"}
            onClick={() => setTab("past")}
          >
            Past winners
          </button>
          <button
            className={tab === "future" ? "tab active" : "tab"}
            onClick={() => setTab("future")}
          >
            Future winners
          </button>
        </nav>

        {tab === "past" ? <PastWinners /> : <FutureWinners />}
      </div>
    </QueryClientProvider>
  );
}
