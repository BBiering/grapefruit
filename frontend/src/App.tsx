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
      <header className="topbar">
        <div className="topbar-inner">
          <div className="brand">
            <span className="brand-mark" aria-hidden="true">🍊</span>
            <span className="brand-name">Grapefruit</span>
          </div>
          <nav className="nav">
            <button
              className={tab === "past" ? "navbtn active" : "navbtn"}
              onClick={() => setTab("past")}
            >
              Past winners
            </button>
            <button
              className={tab === "future" ? "navbtn active" : "navbtn"}
              onClick={() => setTab("future")}
            >
              Future winners
            </button>
          </nav>
        </div>
      </header>

      <main className="app">
        {!hasSupabaseConfig && (
          <div className="card warn">
            <strong>Supabase env vars missing.</strong>{" "}
            Set <code>VITE_SUPABASE_URL</code> and{" "}
            <code>VITE_SUPABASE_PUBLISHABLE_KEY</code> in Vercel project
            settings, then redeploy. Use the <strong>publishable</strong> key
            (<code>sb_publishable_…</code>) — never the secret key, which would
            bypass RLS once inlined into the public bundle.
          </div>
        )}

        {tab === "past" ? <PastWinners /> : <FutureWinners />}
      </main>
    </QueryClientProvider>
  );
}
