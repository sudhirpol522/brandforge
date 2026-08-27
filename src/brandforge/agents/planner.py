from __future__ import annotations

import re

from ..domain import BrandRules, CampaignBrief, CampaignPlan
from .contracts import AgentContract, AgentTrace

CHANNEL_SPECS = {
    "instagram": "1080x1350 portrait post plus accessible caption",
    "email": "1200x600 hero with subject line, preview text, and body",
    "web": "1440x560 responsive hero with concise CTA",
    "presentation": "1920x1080 editable 16:9 title slide",
}


class CampaignPlannerAgent:
    contract = AgentContract(
        name="campaign_planner",
        version="1.0",
        allowed_tools=("brand_rules", "channel_specifications"),
        timeout_seconds=20,
        max_steps=3,
        max_cost_usd=0.03,
        input_schema="CampaignBrief + BrandRules",
        output_schema="CampaignPlan",
        escalation_conditions=("ambiguous audience", "unsupported claims", "unknown channel"),
    )

    def run(
        self, brief: CampaignBrief, rules: BrandRules, revision_note: str = ""
    ) -> tuple[CampaignPlan, AgentTrace]:
        tone = ", ".join(rules.tone[:3])
        key_terms = _keywords(f"{brief.objective} {brief.audience} {brief.product_name}")
        messages = [
            f"{brief.product_name} helps {brief.audience} achieve {brief.objective.lower()}.",
            f"Use a {tone} voice and end with '{brief.call_to_action}'.",
        ]
        if revision_note:
            messages.append(f"Reviewer direction: {revision_note[:240]}")
        claims = [
            sentence.strip()
            for sentence in re.split(r"[.!?]", brief.objective)
            if re.search(r"\b(best|guarantee|proven|number one|always|never)\b", sentence, re.I)
        ]
        plan = CampaignPlan(
            objective=brief.objective,
            audience=brief.audience,
            key_messages=messages,
            visual_direction=(
                f"A {tone} visual system using {', '.join(rules.colors[:3])}; "
                f"focus on {', '.join(key_terms[:5])}."
            ),
            channel_deliverables={
                channel: CHANNEL_SPECS.get(channel, f"brand-compliant {channel} asset")
                for channel in brief.channels
            },
            required_assets=["approved logo", "product image", "brand fonts"],
            claims_requiring_review=claims,
            success_criteria=[
                "brand compliance score >= 0.80",
                "accessibility score >= 0.85",
                "no unsupported claim violations",
                "top variants are visually distinct",
            ],
            revision=2 if revision_note else 1,
        )
        trace = AgentTrace(
            agent=self.contract.name,
            version=self.contract.version,
            decision_summary=f"Planned {len(plan.channel_deliverables)} coordinated deliverables.",
            warnings=["claims need legal review"] if claims else [],
        )
        return plan, trace


def _keywords(text: str) -> list[str]:
    stop = {"and", "for", "from", "that", "the", "this", "with", "your", "into", "our"}
    words = re.findall(r"[a-z0-9]+", text.lower())
    return list(dict.fromkeys(word for word in words if len(word) > 2 and word not in stop))
