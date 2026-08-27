"""BrandForge core package."""

from .domain import Campaign, CampaignBrief, CampaignStatus
from .workflow import BrandForgeWorkflow

__all__ = ["BrandForgeWorkflow", "Campaign", "CampaignBrief", "CampaignStatus"]
__version__ = "0.1.0"
