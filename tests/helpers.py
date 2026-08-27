from pathlib import Path

from brandforge.agents import (
    BrandCompilerAgent,
    CampaignPlannerAgent,
    CreativeAgent,
    MultimodalReranker,
)
from brandforge.domain import CampaignBrief
from brandforge.exporter import CampaignExporter
from brandforge.model_gateway import DeterministicModelProvider, ModelGateway
from brandforge.object_store import LocalObjectStore
from brandforge.persistence import InMemoryCampaignRepository
from brandforge.workflow import BrandForgeWorkflow

GUIDE = """
Example Brand Guide
Primary colors: #112233, #F0A500, #FFFFFF
Typography: Montserrat and Inter.
Voice: energetic, confident, premium.
Logo clear space: 28px. Use a white background.
Do not use: cheap, guaranteed results.
Required legal disclaimer: Terms may apply.
""".strip()


def brief() -> CampaignBrief:
    return CampaignBrief(
        product_name="Example One",
        objective="Launch a premium everyday product for active people.",
        audience="busy university students",
        call_to_action="Find your pace",
    )


def workflow(root: Path) -> BrandForgeWorkflow:
    gateway = ModelGateway(
        DeterministicModelProvider(),
        max_calls_per_campaign=50,
        max_cost_per_campaign_usd=5,
    )
    return BrandForgeWorkflow(
        repository=InMemoryCampaignRepository(),
        brand_compiler=BrandCompilerAgent(),
        planner=CampaignPlannerAgent(),
        creative=CreativeAgent(gateway),
        reranker=MultimodalReranker(),
        exporter=CampaignExporter(LocalObjectStore(root)),
    )
