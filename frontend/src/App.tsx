import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Dashboard } from "./pages/Dashboard";
import { hasSupabaseConfig } from "./supabase";

const qc = new QueryClient({
  defaultOptions: { queries: { retry: 1, staleTime: 60_000 } },
});

export default function App() {
  return (
    <QueryClientProvider client={qc}>
      {!hasSupabaseConfig && (
        <div className="card warn" style={{ margin: "2rem auto", maxWidth: "800px" }}>
          <strong>Supabase env vars missing.</strong> Set <code>VITE_SUPABASE_URL</code> and{" "}
          <code>VITE_SUPABASE_PUBLISHABLE_KEY</code> in Vercel project settings, then redeploy. Use the{" "}
          <strong>publishable</strong> key (<code>sb_publishable_…</code>) — never the secret key, which would bypass
          RLS once inlined into the public bundle.
        </div>
      )}

      <Dashboard />
    </QueryClientProvider>
  );
}
