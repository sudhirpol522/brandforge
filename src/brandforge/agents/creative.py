from __future__ import annotations

import hashlib
import random
from typing import Any

from ..domain import BrandRules, CampaignBrief, CampaignPlan, CampaignVariant
from ..model_gateway import ModelGateway
from .contracts import AgentContract, AgentTrace

CONCEPTS = (
    ("Momentum", "dynamic movement, directional light, decisive typography"),
    ("Precision", "clean geometry, premium negative space, detailed product focus"),
    ("Human Spark", "authentic people, warm moments, optimistic energy"),
    ("Future Field", "layered gradients, bold depth, modern editorial composition"),
    ("Quiet Confidence", "minimal layout, soft texture, restrained product storytelling"),
    ("Community Pulse", "diverse scenes, rhythmic collage, candid energy"),
    ("Proof in Motion", "product detail, credible demonstration, outcome-led framing"),
    ("New Ritual", "everyday context, tactile close-ups, calm aspirational tone"),
)


class CreativeAgent:
    contract = AgentContract(
        name="creative_studio",
        version="1.0",
        allowed_tools=("model_gateway.text", "model_gateway.image", "approved_assets"),
        timeout_seconds=120,
        max_steps=20,
        max_cost_usd=3.0,
        input_schema="CampaignPlan + BrandRules",
        output_schema="list[CampaignVariant]",
        escalation_conditions=("budget exceeded", "provider unavailable", "missing product asset"),
    )

    def __init__(self, gateway: ModelGateway) -> None:
        self.gateway = gateway

    def run(
        self,
        campaign_id: str,
        brief: CampaignBrief,
        rules: BrandRules,
        plan: CampaignPlan,
        count: int = 8,
        revision_note: str = "",
        reference_context: list[dict[str, Any]] | None = None,
    ) -> tuple[list[CampaignVariant], AgentTrace]:
        count = max(3, min(count, len(CONCEPTS)))
        cost_before = self.gateway.usage(campaign_id).estimated_cost_usd
        seed_base = int(hashlib.sha256(campaign_id.encode()).hexdigest()[:12], 16)
        variants: list[CampaignVariant] = []
        tool_calls = []
        approved_reference_text = _reference_text(reference_context or [])
        for index, (concept, visual_style) in enumerate(CONCEPTS[:count]):
            seed = seed_base + index + plan.revision * 1000
            rng = random.Random(seed)
            prompt = (
                f"{brief.product_name} campaign for {brief.audience}; objective {brief.objective}; "
                f"concept {concept}; {visual_style}; tone {', '.join(rules.tone[:3])}."
                f"{approved_reference_text}"
            )
            headline = self.gateway.generate_text(campaign_id, "headline", prompt, seed)
            body = self.gateway.generate_text(
                campaign_id,
                "body_copy",
                f"{prompt} CTA {brief.call_to_action}. Keep claims conservative.",
                seed + 73,
            )
            palette = list(rules.colors[:3])
            inject_first_candidate_fault = index == 0 and seed_base % 3 == 0
            if index == count - 1 or inject_first_candidate_fault:
                # A deliberate off-brand candidate makes critic and reranking behavior observable.
                palette = ["#FF00FF", "#00FFFF"]
            elif len(palette) > 1:
                rng.shuffle(palette)
            visual_prompt = (
                f"{visual_style}; product: {brief.product_name}; audience: {brief.audience}; "
                f"brand palette: {', '.join(palette)}; no embedded text; {revision_note[:120]}"
            ).strip()
            copy = {
                channel: _channel_copy(channel, headline, body, brief.call_to_action)
                for channel in brief.channels
            }
            if index == 0 and seed_base % 5 == 0:
                for channel_copy in copy.values():
                    channel_copy["body"] = (
                        channel_copy.get("body", channel_copy.get("caption", ""))
                        + " Guaranteed results."
                    )
            identity = f"{campaign_id}:{index}:{plan.revision}".encode()
            variant_id = f"var_{hashlib.sha256(identity).hexdigest()[:12]}"
            variants.append(
                CampaignVariant(
                    id=variant_id,
                    concept=concept,
                    rationale=(
                        f"Uses {visual_style} to support {brief.objective.lower()} for "
                        f"{brief.audience}."
                    ),
                    copy_by_channel=copy,
                    visual_prompt=visual_prompt,
                    alt_text=(
                        f"{brief.product_name} shown in the {concept.lower()} campaign direction "
                        f"for {brief.audience}."
                    ),
                    image_tags=_tags(prompt),
                    palette=palette,
                    estimated_cost_usd=0.02,
                )
            )
            tool_calls.append({"tool": "model_gateway.text", "variant_id": variant_id, "calls": 2})
        if reference_context:
            tool_calls.append(
                {
                    "tool": "approved_assets",
                    "retrieval_ids": [
                        str(item["retrieval_id"])
                        for item in reference_context
                        if item.get("retrieval_id")
                    ],
                }
            )
        usage = self.gateway.usage(campaign_id)
        trace = AgentTrace(
            agent=self.contract.name,
            version=self.contract.version,
            decision_summary=f"Generated {len(variants)} coordinated campaign directions.",
            tool_calls=tool_calls,
            cost_usd=round(usage.estimated_cost_usd - cost_before, 6),
        )
        return variants, trace

    def render_and_score(
        self,
        campaign_id: str,
        brief: CampaignBrief,
        rules: BrandRules,
        variant: CampaignVariant,
    ) -> tuple[dict[str, object], dict[str, float] | None, AgentTrace]:
        cost_before = self.gateway.usage(campaign_id).estimated_cost_usd
        seed = int(
            hashlib.sha256(f"{campaign_id}:{variant.id}:render".encode()).hexdigest()[:12], 16
        )
        image = self.gateway.generate_image(
            campaign_id,
            variant.visual_prompt,
            width=1024,
            height=1024,
            seed=seed,
        )
        vision_scores = None
        image_base64 = image.get("image_base64")
        media_type = str(image.get("media_type", "image/png"))
        if isinstance(image_base64, str) and image_base64:
            vision_scores = self.gateway.analyze_image(
                campaign_id,
                prompt=(
                    f"Product: {brief.product_name}\nObjective: {brief.objective}\n"
                    f"Audience: {brief.audience}\nApproved colors: {rules.colors}\n"
                    f"Tone: {rules.tone}\nConcept: {variant.concept}"
                ),
                image_base64=image_base64,
                media_type=media_type,
                seed=seed + 1,
            )
        usage = self.gateway.usage(campaign_id)
        trace = AgentTrace(
            agent="visual_generation_and_critic",
            version="1.0",
            decision_summary=f"Rendered and visually evaluated {variant.concept}.",
            tool_calls=[
                {"tool": "model_gateway.image", "variant_id": variant.id},
                {
                    "tool": "model_gateway.vision",
                    "variant_id": variant.id,
                    "executed": vision_scores is not None,
                },
            ],
            warnings=[]
            if vision_scores
            else ["provider returned no inline image for vision scoring"],
            cost_usd=round(usage.estimated_cost_usd - cost_before, 6),
        )
        return image, vision_scores, trace

    def provider_manifest(self) -> dict[str, str]:
        provider = self.gateway.provider
        manifest = {
            "provider": provider.name,
            "text_model": provider.model_name,
        }
        for attribute, key in (("vision_model", "vision_model"), ("image_model", "image_model")):
            if value := getattr(provider, attribute, None):
                manifest[key] = str(value)
        return manifest


def _channel_copy(channel: str, headline: str, body: str, call_to_action: str) -> dict[str, str]:
    if channel == "email":
        return {
            "headline": headline,
            "subject": headline[:58],
            "preview": body[:90],
            "body": body[:420],
            "cta": call_to_action,
        }
    if channel == "instagram":
        return {
            "headline": headline,
            "caption": f"{body[:260]} #{''.join(headline.split()[:2])}",
            "cta": call_to_action,
        }
    return {"headline": headline, "body": body[:220], "cta": call_to_action}


def _tags(text: str) -> list[str]:
    words = [word.strip(".,:;").lower() for word in text.split()]
    stop = {"the", "and", "for", "with", "tone", "objective", "campaign", "concept"}
    return list(dict.fromkeys(word for word in words if len(word) > 3 and word not in stop))[:16]


def _reference_text(references: list[dict[str, Any]]) -> str:
    snippets: list[str] = []
    for reference in references[:5]:
        content = reference.get("content")
        if isinstance(content, str) and content.strip():
            snippets.append(" ".join(content.split())[:300])
    if not snippets:
        return ""
    return " Approved reference context: " + " | ".join(snippets)
