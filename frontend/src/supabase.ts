import { createClient } from "@supabase/supabase-js";

const url = import.meta.env.VITE_SUPABASE_URL;
const anonKey = import.meta.env.VITE_SUPABASE_ANON_KEY;

if (!url || !anonKey) {
  // Surfaced by App.tsx as a banner instead of a white screen.
  console.warn(
    "Supabase env vars missing: set VITE_SUPABASE_URL and VITE_SUPABASE_ANON_KEY in Vercel."
  );
}

export const supabase = createClient(url ?? "http://localhost", anonKey ?? "anon");

export const hasSupabaseConfig = Boolean(url && anonKey);
