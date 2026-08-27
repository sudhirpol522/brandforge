import type { Scores } from "@/lib/types";

const LABELS: Array<[keyof Scores, string]> = [
  ["brief_alignment", "Brief"],
  ["visual_alignment", "Visual"],
  ["brand_compliance", "Brand"],
  ["visual_quality", "Quality"],
  ["accessibility", "A11y"],
  ["claims_safety", "Claims"]
];

export function ScorePanel({ scores }: { scores: Scores }) {
  return (
    <div className="score-panel" aria-label="Evaluation scores">
      {LABELS.map(([key, label]) => {
        const value = Number(scores[key]);
        return (
          <div className="score-row" key={key}>
            <span>{label}</span>
            <div className="score-track" aria-hidden="true">
              <i style={{ width: String(Math.round(value * 100)) + "%" }} />
            </div>
            <strong>{Math.round(value * 100)}</strong>
          </div>
        );
      })}
    </div>
  );
}
