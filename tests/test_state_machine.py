import unittest

from brandforge.domain import CampaignStatus
from brandforge.exceptions import InvalidTransitionError
from brandforge.state_machine import assert_transition


class StateMachineTests(unittest.TestCase):
    def test_valid_happy_path_transition(self) -> None:
        assert_transition(
            CampaignStatus.BRAND_RULES_PENDING_APPROVAL,
            CampaignStatus.PLAN_PENDING_APPROVAL,
        )

    def test_cannot_skip_human_gate(self) -> None:
        with self.assertRaises(InvalidTransitionError):
            assert_transition(CampaignStatus.CREATED, CampaignStatus.GENERATING)

    def test_completed_can_only_return_to_final_approval(self) -> None:
        assert_transition(CampaignStatus.COMPLETED, CampaignStatus.FINAL_APPROVAL)
        with self.assertRaises(InvalidTransitionError):
            assert_transition(CampaignStatus.COMPLETED, CampaignStatus.REVISING)

    def test_provider_failure_can_retry(self) -> None:
        assert_transition(CampaignStatus.FAILED_RETRYABLE, CampaignStatus.GENERATING)

    def test_cancellation_is_allowed_during_review(self) -> None:
        assert_transition(CampaignStatus.PLAN_PENDING_APPROVAL, CampaignStatus.CANCELLED)
