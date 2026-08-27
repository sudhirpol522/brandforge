from __future__ import annotations

from dataclasses import dataclass

from ..domain import BrandRules, CampaignBrief, CampaignVariant
from .contracts import AgentContract, AgentTrace
from .critics import CampaignCritics, variant_similarity
from .preferences import PairwisePreferenceModel


@dataclass(frozen=True, slots=True)
class RankingWeights:
    brief_alignment: float = 0.18
    visual_alignment: float = 0.13
    copy_image_consistency: float = 0.09
    visual_quality: float = 0.09
    brand_compliance: float = 0.18
    accessibility: float = 0.09
    claims_safety: float = 0.09
    preference: float = 0.10
    diversity: float = 0.05


class MultimodalReranker:
    contract = AgentContract(
        name="multimodal_reranker",
        version="1.0",
        allowed_tools=("campaign_critics", "preference_model", "diversity_mmr"),
        timeout_seconds=45,
        max_steps=30,
        max_cost_usd=0.20,
        input_schema="CampaignBrief + BrandRules + list[CampaignVariant]",
        output_schema="ranked list[CampaignVariant]",
        escalation_conditions=("top score below 0.65", "all variants violate brand policy"),
    )

    def __init__(
        self,
        critics: CampaignCritics | None = None,
        preference_model: PairwisePreferenceModel | None = None,
        weights: RankingWeights | None = None,
        diversity_lambda: float = 0.12,
    ) -> None:
        self.critics = critics or CampaignCritics()
        self.preference_model = preference_model or PairwisePreferenceModel()
        self.weights = weights or RankingWeights()
        self.diversity_lambda = diversity_lambda

    def run(
        self,
        brief: CampaignBrief,
        rules: BrandRules,
        variants: list[CampaignVariant],
        top_k: int = 3,
        external_visual_scores: dict[str, dict[str, float]] | None = None,
    ) -> tuple[list[CampaignVariant], AgentTrace]:
        for variant in variants:
            result = self.critics.evaluate(brief, rules, variant)
            variant.scores = result.scores
            variant.violations = result.violations
            if external := (external_visual_scores or {}).get(variant.id):
                variant.scores.visual_alignment = round(
                    0.35 * variant.scores.visual_alignment + 0.65 * external["brief_alignment"],
                    4,
                )
                variant.scores.brand_compliance = round(
                    0.45 * variant.scores.brand_compliance + 0.55 * external["brand_alignment"],
                    4,
                )
                variant.scores.visual_quality = round(external["composition_quality"], 4)
                variant.scores.scorer_mode = "provider_vision_plus_deterministic_critics"
            variant.scores.preference = round(self.preference_model.predict(variant.scores), 4)
            variant.scores.final = round(self._base_score(variant), 4)

        remaining = sorted(variants, key=lambda item: item.scores.final, reverse=True)
        ranked: list[CampaignVariant] = []
        while remaining:
            best: CampaignVariant | None = None
            best_adjusted = -1.0
            for candidate in remaining:
                max_similarity = max(
                    (variant_similarity(candidate, chosen) for chosen in ranked), default=0.0
                )
                candidate.scores.diversity = round(1.0 - max_similarity, 4)
                adjusted = candidate.scores.final - self.diversity_lambda * max_similarity
                if adjusted > best_adjusted:
                    best, best_adjusted = candidate, adjusted
            assert best is not None
            best.scores.final = round(max(0.0, min(1.0, best_adjusted)), 4)
            best.rank = len(ranked) + 1
            ranked.append(best)
            remaining.remove(best)

        warnings = []
        if ranked and ranked[0].scores.final < 0.65:
            warnings.append("top score below automatic recommendation threshold")
        if ranked and all(item.scores.brand_compliance < 0.7 for item in ranked):
            warnings.append("all candidates require brand review")
        trace = AgentTrace(
            agent=self.contract.name,
            version=self.contract.version,
            decision_summary=(
                f"Evaluated {len(ranked)} variants and selected {min(top_k, len(ranked))} "
                "with diversity-aware ranking."
            ),
            tool_calls=[
                {"tool": "campaign_critics", "calls": len(ranked)},
                {
                    "tool": "provider_vision",
                    "calls": len(external_visual_scores or {}),
                },
                {
                    "tool": "preference_model",
                    "version": self.preference_model.model_version,
                },
                {"tool": "diversity_mmr", "lambda": self.diversity_lambda},
            ],
            warnings=warnings,
        )
        return ranked[: max(1, top_k)], trace

    def _base_score(self, variant: CampaignVariant) -> float:
        scores = variant.scores
        weights = self.weights
        return (
            weights.brief_alignment * scores.brief_alignment
            + weights.visual_alignment * scores.visual_alignment
            + weights.copy_image_consistency * scores.copy_image_consistency
            + weights.visual_quality * scores.visual_quality
            + weights.brand_compliance * scores.brand_compliance
            + weights.accessibility * scores.accessibility
            + weights.claims_safety * scores.claims_safety
            + weights.preference * scores.preference
            + weights.diversity * scores.diversity
        )
