import { formatScore, getQualityLevel, getQualityLabel } from "../utils";

interface QualityBadgeProps {
  score: number;
}

export function QualityBadge({ score }: QualityBadgeProps) {
  const level = getQualityLevel(score);
  const label = getQualityLabel(score);

  return (
    <div className="quality-badge">
      <span className="score">{formatScore(score)}</span>
      <span className={`badge ${level}`}>{label}</span>
    </div>
  );
}
