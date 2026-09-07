import { useMutation, useQueryClient } from "@tanstack/react-query";
import { supabase } from "../supabase";

interface Props {
  symbol: string;
  isSaved: boolean;
}

export function WatchlistButton({ symbol, isSaved }: Props) {
  const qc = useQueryClient();

  const toggle = useMutation({
    mutationFn: async () => {
      if (isSaved) {
        const { error } = await supabase.from("watchlist").delete().eq("symbol", symbol);
        if (error) throw error;
      } else {
        const { error } = await supabase.from("watchlist").insert({ symbol });
        if (error) throw error;
      }
    },
    onSuccess: () => {
      // Keep the cached set in sync without a refetch.
      qc.setQueryData<Set<string>>(["watchlist"], (prev) => {
        const next = new Set(prev ?? []);
        isSaved ? next.delete(symbol) : next.add(symbol);
        return next;
      });
    },
  });

  return (
    <button
      className={`watchlist-btn ${isSaved ? "saved" : ""}`}
      onClick={(e) => { e.stopPropagation(); toggle.mutate(); }}
      title={isSaved ? "Remove from watchlist" : "Save to watchlist"}
      aria-label={isSaved ? "Remove from watchlist" : "Save to watchlist"}
    >
      {isSaved ? "★" : "☆"}
    </button>
  );
}