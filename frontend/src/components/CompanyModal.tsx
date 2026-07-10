import { useQuery } from "@tanstack/react-query";
import { supabase } from "../supabase";
import type { CompanyCard } from "../types";
import { CompanyChart } from "./CompanyChart";
import { StatsGrid } from "./StatsGrid";
import { CatalystCard } from "./CatalystCard";

interface Bar {
  ts: string;
  close: number;
}

async function fetchBars(symbol: string): Promise<Bar[]> {
  const { data, error } = await supabase.from("bars").select("ts, close").eq("symbol", symbol).order("ts", { ascending: true });
  if (error) throw error;
  return (data ?? []) as Bar[];
}

interface CompanyModalProps {
  company: CompanyCard;
  onClose: () => void;
  onNext: () => void;
  onPrev: () => void;
}

export function CompanyModal({ company, onClose, onNext, onPrev }: CompanyModalProps) {
  const { data: bars = [] } = useQuery({
    queryKey: ["bars", company.symbol],
    queryFn: () => fetchBars(company.symbol),
    staleTime: 10 * 60 * 1000, // 10 minutes
  });

  // Debug: Log catalyst data
  console.log(`[CompanyModal] ${company.symbol} catalyst data:`, {
    predicted_catalyst: company.predicted_catalyst,
    forward_catalyst: company.forward_catalyst,
  });

  // Handle keyboard navigation
  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Escape") onClose();
    if (e.key === "ArrowLeft") onPrev();
    if (e.key === "ArrowRight") onNext();
  };

  return (
    <div className="modal-overlay" onClick={onClose} onKeyDown={handleKeyDown} tabIndex={0}>
      {/* Navigation arrows */}
      <button className="modal-nav modal-nav-prev" onClick={(e) => { e.stopPropagation(); onPrev(); }} aria-label="Previous company">
        ‹
      </button>
      <button className="modal-nav modal-nav-next" onClick={(e) => { e.stopPropagation(); onNext(); }} aria-label="Next company">
        ›
      </button>

      <div className="modal-content fullscreen" onClick={(e) => e.stopPropagation()}>
        <button className="modal-close" onClick={onClose} aria-label="Close modal">
          ×
        </button>

        {/* Header */}
        <div className="modal-header">
          <h2>
            {company.symbol} - {company.name}
          </h2>
          <p className="muted">
            {company.sector} / {company.industry}
          </p>
        </div>

        {/* Full Chart */}
        <CompanyChart
          bars={bars}
          recentMove={company.recent_move}
          winnerEvent={company.winner_event}
          catalyst={company.predicted_catalyst || company.forward_catalyst}
          recentStepChange={company.recent_step_change}
        />

        {/* Stats Grid */}
        <StatsGrid company={company} />

        {/* Explanation Cards */}
        <div className="explanation-cards">
          {company.type === "future" ? (
            <>
              {/* Forward Catalyst Card */}
              {(company.predicted_catalyst?.detected || company.forward_catalyst?.detected) && (
                <CatalystCard catalyst={company.predicted_catalyst || company.forward_catalyst!} />
              )}

              {/* Upcoming Events Card */}
              {company.upcoming_events && company.upcoming_events.length > 0 && (
                <div className="card explanation">
                  <div className="explanation-head">
                    <h3>Next Earnings</h3>
                    <span className="badge">Scheduled</span>
                  </div>
                  <div className="explanation-body">
                    <p>
                      <strong>Date:</strong> {company.upcoming_events[0].event_ts}
                    </p>
                    <p>
                      <strong>Event:</strong> {company.upcoming_events[0].title || "Earnings Report"}
                    </p>
                  </div>
                </div>
              )}
            </>
          ) : (
            <>
              {/* Past Winner: Catalyst Explanation */}
              {company.headline && (
                <div className="card explanation">
                  <div className="explanation-head">
                    <h3>Catalyst</h3>
                    <span className="badge">Historical</span>
                  </div>
                  <div className="explanation-body">
                    <h4>{company.headline}</h4>
                    <p>{company.summary}</p>
                  </div>
                </div>
              )}

              {/* Spike Explanation */}
              {company.spike_explanation && (
                <div className="card explanation">
                  <div className="explanation-head">
                    <h3>Spike Explanation</h3>
                  </div>
                  <div className="explanation-body">
                    <p>{company.spike_explanation}</p>
                  </div>
                </div>
              )}

              {/* Foreseeable Evidence */}
              {company.foreseeable_evidence && (
                <div className="card explanation">
                  <div className="explanation-head">
                    <h3>Foreseeable Evidence</h3>
                    <span className={`badge ${company.was_foreseeable ? "yes" : "no"}`}>
                      {company.was_foreseeable ? "Yes" : "No"}
                    </span>
                  </div>
                  <div className="explanation-body">
                    <p>{company.foreseeable_evidence}</p>
                  </div>
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
}
