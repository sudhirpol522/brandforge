from __future__ import annotations

import math
import re
from dataclasses import dataclass

from ..domain import BrandRules, CampaignBrief, CampaignVariant, ScoreBreakdown


@dataclass(frozen=True, slots=True)
class CriticResult:
    scores: ScoreBreakdown
    violations: list[str]


class CampaignCritics:
    def evaluate(
        self, brief: CampaignBrief, rules: BrandRules, variant: CampaignVariant
    ) -> CriticResult:
        all_copy = " ".join(
            value for channel in variant.copy_by_channel.values() for value in channel.values()
        )
        brief_text = f"{brief.product_name} {brief.objective} {brief.audience}"
        visual_text = f"{variant.visual_prompt} {variant.alt_text} {' '.join(variant.image_tags)}"
        violations: list[str] = []

        brief_alignment = _semantic_overlap(brief_text, f"{all_copy} {visual_text}")
        visual_alignment = _semantic_overlap(brief_text, visual_text)
        copy_image = _semantic_overlap(all_copy, visual_text)

        approved_colors = {color.upper() for color in rules.colors}
        candidate_colors = {color.upper() for color in variant.palette}
        color_match = len(approved_colors & candidate_colors) / max(1, len(candidate_colors))
        prohibited_hits = [
            term for term in rules.prohibited_terms if term.lower() in all_copy.lower()
        ]
        if prohibited_hits:
            violations.extend(f"prohibited term: {term}" for term in prohibited_hits)
        if color_match < 0.5:
            violations.append("palette does not match approved brand colors")
        brand = max(0.0, min(1.0, 0.55 + 0.45 * color_match - 0.2 * len(prohibited_hits)))

        contrast = _palette_contrast(variant.palette)
        alt_score = 1.0 if len(variant.alt_text.split()) >= 8 else 0.5
        accessibility = 0.7 * contrast + 0.3 * alt_score
        if contrast < 0.7:
            violations.append("palette contrast requires accessibility review")
        if alt_score < 1.0:
            violations.append("alt text is too short")

        risky_claims = re.findall(
            r"\b(guaranteed?|best|number\s+one|proven|always|never|cure[sd]?)\b", all_copy, re.I
        )
        claims_safety = max(0.0, 1.0 - 0.25 * len(risky_claims))
        if risky_claims:
            violations.extend(f"claim requires evidence: {claim}" for claim in risky_claims)

        scores = ScoreBreakdown(
            brief_alignment=round(brief_alignment, 4),
            visual_alignment=round(visual_alignment, 4),
            copy_image_consistency=round(copy_image, 4),
            visual_quality=round(0.55 + 0.25 * visual_alignment + 0.2 * alt_score, 4),
            brand_compliance=round(brand, 4),
            accessibility=round(accessibility, 4),
            claims_safety=round(claims_safety, 4),
        )
        return CriticResult(scores=scores, violations=list(dict.fromkeys(violations)))


def _tokens(value: str) -> set[str]:
    stop = {
        "about",
        "campaign",
        "from",
        "into",
        "that",
        "the",
        "this",
        "tone",
        "using",
        "with",
    }
    return {
        token
        for token in re.findall(r"[a-z0-9]+", value.lower())
        if len(token) > 2 and token not in stop
    }


def _semantic_overlap(left: str, right: str) -> float:
    left_tokens = _tokens(left)
    right_tokens = _tokens(right)
    if not left_tokens or not right_tokens:
        return 0.0
    recall = len(left_tokens & right_tokens) / len(left_tokens)
    precision = len(left_tokens & right_tokens) / len(right_tokens)
    f1 = 2 * precision * recall / max(1e-9, precision + recall)
    return min(1.0, 0.35 + 0.65 * math.sqrt(max(0.0, f1)))


def _palette_contrast(palette: list[str]) -> float:
    valid = [color for color in palette if re.fullmatch(r"#[0-9A-Fa-f]{6}", color)]
    if len(valid) < 2:
        return 0.5
    ratios = [
        _contrast_ratio(left, right)
        for index, left in enumerate(valid)
        for right in valid[index + 1 :]
    ]
    best = max(ratios, default=1.0)
    return min(1.0, best / 7.0)


def _contrast_ratio(left: str, right: str) -> float:
    high, low = sorted((_luminance(left), _luminance(right)), reverse=True)
    return (high + 0.05) / (low + 0.05)


def _luminance(color: str) -> float:
    components = [int(color[index : index + 2], 16) / 255 for index in (1, 3, 5)]
    linear = [
        value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4
        for value in components
    ]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def variant_similarity(left: CampaignVariant, right: CampaignVariant) -> float:
    left_text = f"{left.concept} {left.visual_prompt} {' '.join(left.image_tags)}"
    right_text = f"{right.concept} {right.visual_prompt} {' '.join(right.image_tags)}"
    a, b = _tokens(left_text), _tokens(right_text)
    text_similarity = len(a & b) / max(1, len(a | b))
    palette_a, palette_b = set(left.palette), set(right.palette)
    palette_similarity = len(palette_a & palette_b) / max(1, len(palette_a | palette_b))
    return 0.75 * text_similarity + 0.25 * palette_similarity
