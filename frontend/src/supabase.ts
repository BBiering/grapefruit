import { createClient } from "@supabase/supabase-js";

const url = import.meta.env.VITE_SUPABASE_URL;
// IMPORTANT: this must be the **publishable** key (sb_publishable_...), not the
// secret key. Vite inlines every VITE_* var into the public JS bundle, so the
// secret key would be visible to anyone loading the site and would bypass RLS.
const publishableKey = import.meta.env.VITE_SUPABASE_PUBLISHABLE_KEY;

if (!url || !publishableKey) {
  // Surfaced by App.tsx as a banner instead of a white screen.
  console.warn(
    "Supabase env vars missing: set VITE_SUPABASE_URL and VITE_SUPABASE_PUBLISHABLE_KEY in Vercel."
  );
}

export const supabase = createClient(url ?? "http://localhost", publishableKey ?? "anon");

export const hasSupabaseConfig = Boolean(url && publishableKey);
