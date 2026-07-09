import type { ForwardCatalyst } from "../types";

interface CatalystCardProps {
  catalyst: ForwardCatalyst;
}

export function CatalystCard({ catalyst }: CatalystCardProps) {
  return (
    <div className="card explanation">
      <div className="explanation-head">
        <h3>{catalyst.event_name || "Forward Catalyst"}</h3>
        {catalyst.impact_type && <span className="badge">{catalyst.impact_type}</span>}
      </div>
      <div className="explanation-body">
        {catalyst.strategic_summary && <p>{catalyst.strategic_summary}</p>}
        {catalyst.expected_window && (
          <p>
            <strong>Expected Window:</strong> {catalyst.expected_window}
          </p>
        )}
        {catalyst.source_url && (
          <p>
            <strong>Source:</strong>{" "}
            <a href={catalyst.source_url} target="_blank" rel="noopener noreferrer">
              View source
            </a>
          </p>
        )}
      </div>
    </div>
  );
}
