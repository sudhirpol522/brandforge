from __future__ import annotations

from pathlib import Path

from .agents import (
    BrandCompilerAgent,
    CampaignPlannerAgent,
    CreativeAgent,
    MultimodalReranker,
)
from .domain import ApprovalDecision, CampaignBrief
from .exporter import CampaignExporter
from .model_gateway import DeterministicModelProvider, ModelGateway
from .object_store import LocalObjectStore
from .persistence import SQLiteCampaignRepository
from .workflow import BrandForgeWorkflow

DEMO_GUIDE = """
Aster Run Brand Guide
Primary colors: #182A4D, #F4B942, #FFFFFF
Typography: Montserrat headlines and Inter body copy.
Voice: energetic, confident, premium, inclusive.
Logo clear space: 32px. Use the logo on white or navy backgrounds.
Do not use: cheap, guaranteed results, no pain.
Required legal disclaimer: Product performance varies by user.
""".strip()


def build_demo_workflow(root: Path) -> BrandForgeWorkflow:
    gateway = ModelGateway(
        DeterministicModelProvider(),
        max_calls_per_campaign=50,
        max_cost_per_campaign_usd=5,
    )
    return BrandForgeWorkflow(
        repository=SQLiteCampaignRepository(root / "brandforge.db"),
        brand_compiler=BrandCompilerAgent(),
        planner=CampaignPlannerAgent(),
        creative=CreativeAgent(gateway),
        reranker=MultimodalReranker(),
        exporter=CampaignExporter(LocalObjectStore(root / "objects")),
    )


def main() -> None:
    root = Path(".brandforge/demo").resolve()
    workflow = build_demo_workflow(root)
    tenant = "demo-studio"
    reviewer = "creative-director"
    campaign = workflow.create_campaign(
        tenant,
        "Aster Run — Campus Launch",
        CampaignBrief(
            product_name="Aster Run One",
            objective=(
                "Launch a lightweight running shoe that makes everyday movement feel "
                "premium and achievable."
            ),
            audience="university students and first-time runners",
            call_to_action="Find your pace",
        ),
    )
    print(f"1/6 campaign created             {campaign.status}")
    campaign = workflow.compile_brand_guide(tenant, campaign.id, DEMO_GUIDE)
    print(f"2/6 brand rules compiled         {campaign.status}")
    campaign = workflow.review_brand_rules(
        tenant,
        campaign.id,
        reviewer,
        "brand_reviewer",
        ApprovalDecision.APPROVED,
        "Palette and voice confirmed.",
    )
    print(f"3/6 brand rules approved         {campaign.status}")
    campaign = workflow.review_plan(
        tenant,
        campaign.id,
        reviewer,
        "campaign_owner",
        ApprovalDecision.APPROVED,
        "Strategy approved for generation.",
    )
    print(f"4/6 concepts generated + ranked  {campaign.status}")
    recommended = campaign.variants[0]
    campaign = workflow.select_variant(
        tenant,
        campaign.id,
        reviewer,
        "campaign_owner",
        recommended.id,
        "brand_match",
        "Highest ranked direction with strong brand and accessibility scores.",
    )
    print(f"5/6 variant selected             {campaign.status}")
    campaign = workflow.review_final(
        tenant,
        campaign.id,
        reviewer,
        "legal_reviewer",
        ApprovalDecision.APPROVED,
        "Claims and final layouts approved.",
    )
    print(f"6/6 campaign exported            {campaign.status}")
    print()
    print(f"Campaign: {campaign.id}")
    print(f"Selected: {recommended.concept} ({recommended.scores.final:.3f})")
    print(f"Events:   {len(workflow.events(tenant, campaign.id))}")
    print("Cost:     $" + f"{campaign.total_cost_usd:.4f} fixture estimate")
    assert campaign.export is not None
    print(f"Manifest: {root / 'objects' / campaign.export.object_key}")


if __name__ == "__main__":
    main()
