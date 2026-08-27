from __future__ import annotations

from .domain import CampaignStatus
from .exceptions import InvalidTransitionError

ALLOWED_TRANSITIONS: dict[CampaignStatus, set[CampaignStatus]] = {
    CampaignStatus.CREATED: {
        CampaignStatus.ASSETS_PROCESSING,
        CampaignStatus.BRAND_RULES_PENDING_APPROVAL,
        CampaignStatus.CANCELLED,
    },
    CampaignStatus.ASSETS_PROCESSING: {
        CampaignStatus.BRAND_RULES_PENDING_APPROVAL,
        CampaignStatus.FAILED_RETRYABLE,
        CampaignStatus.FAILED_PERMANENT,
        CampaignStatus.CANCELLED,
    },
    CampaignStatus.BRAND_RULES_PENDING_APPROVAL: {
        CampaignStatus.PLAN_PENDING_APPROVAL,
        CampaignStatus.ASSETS_PROCESSING,
        CampaignStatus.CANCELLED,
    },
    CampaignStatus.PLAN_PENDING_APPROVAL: {
        CampaignStatus.GENERATING,
        CampaignStatus.CANCELLED,
    },
    CampaignStatus.GENERATING: {
        CampaignStatus.EVALUATING,
        CampaignStatus.FAILED_RETRYABLE,
        CampaignStatus.FAILED_PERMANENT,
        CampaignStatus.CANCELLED,
    },
    CampaignStatus.EVALUATING: {
        CampaignStatus.VARIANTS_PENDING_APPROVAL,
        CampaignStatus.FAILED_RETRYABLE,
        CampaignStatus.FAILED_PERMANENT,
        CampaignStatus.CANCELLED,
    },
    CampaignStatus.VARIANTS_PENDING_APPROVAL: {
        CampaignStatus.FINAL_APPROVAL,
        CampaignStatus.REVISING,
        CampaignStatus.CANCELLED,
    },
    CampaignStatus.REVISING: {
        CampaignStatus.GENERATING,
        CampaignStatus.CANCELLED,
    },
    CampaignStatus.FINAL_APPROVAL: {
        CampaignStatus.EXPORTING,
        CampaignStatus.REVISING,
        CampaignStatus.CANCELLED,
    },
    CampaignStatus.EXPORTING: {
        CampaignStatus.COMPLETED,
        CampaignStatus.FAILED_RETRYABLE,
        CampaignStatus.FAILED_PERMANENT,
    },
    CampaignStatus.FAILED_RETRYABLE: {
        CampaignStatus.ASSETS_PROCESSING,
        CampaignStatus.GENERATING,
        CampaignStatus.EVALUATING,
        CampaignStatus.EXPORTING,
        CampaignStatus.CANCELLED,
    },
    CampaignStatus.FAILED_PERMANENT: set(),
    CampaignStatus.COMPLETED: {CampaignStatus.FINAL_APPROVAL},
    CampaignStatus.CANCELLED: set(),
}


def assert_transition(current: CampaignStatus, target: CampaignStatus) -> None:
    if target not in ALLOWED_TRANSITIONS[current]:
        raise InvalidTransitionError(f"cannot transition campaign from {current} to {target}")
