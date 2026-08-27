"use client";

import type { CampaignStatus } from "@/lib/types";

const STEPS = [
  ["brief", ["created", "assets_processing"]],
  ["brand rules", ["brand_rules_pending_approval"]],
  ["strategy", ["plan_pending_approval"]],
  ["create + rank", ["generating", "evaluating", "variants_pending_approval"]],
  ["final review", ["final_approval", "revising", "exporting"]],
  ["export", ["completed"]]
] as const;

export function ProgressRail({ status }: { status: CampaignStatus }) {
  const activeIndex = Math.max(
    0,
    STEPS.findIndex(([, states]) => (states as readonly string[]).includes(status))
  );
  return (
    <ol className="progress-rail" aria-label="Campaign workflow progress">
      {STEPS.map(([label], index) => (
        <li
          className={index < activeIndex ? "done" : index === activeIndex ? "active" : ""}
          key={label}
        >
          <div className="progress-node">
            <span>{index < activeIndex ? "✓" : index + 1}</span>
            <small>{label}</small>
          </div>
        </li>
      ))}
    </ol>
  );
}
