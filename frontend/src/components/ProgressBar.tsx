import type { Job } from "../types";

export default function ProgressBar({ job }: { job: Job | null }) {
  if (!job) return null;
  const pct = job.total > 0 ? Math.round((job.processed / job.total) * 100) : 0;
  return (
    <div className="card">
      <div className="row">
        <strong>{job.kind}</strong>
        <span className="muted">{job.status}</span>
        <span className="muted">
          {job.processed} / {job.total} ({pct}%)
        </span>
      </div>
      <div className="progress">
        <div style={{ width: `${pct}%` }} />
      </div>
      {job.message && <div className="muted">{job.message}</div>}
      {job.error && <div style={{ color: "crimson", whiteSpace: "pre-wrap" }}>{job.error}</div>}
    </div>
  );
}
