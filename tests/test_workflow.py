import tempfile
import unittest
from pathlib import Path

from brandforge.domain import ApprovalDecision, CampaignStatus
from brandforge.exceptions import InvalidTransitionError, ValidationError
from tests.helpers import GUIDE, brief, workflow


class WorkflowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.workflow = workflow(Path(self.temp.name))
        self.tenant = "tenant-a"
        self.campaign = self.workflow.create_campaign(self.tenant, "Launch", brief())

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _to_variants(self):
        campaign = self.workflow.compile_brand_guide(self.tenant, self.campaign.id, GUIDE)
        campaign = self.workflow.review_brand_rules(
            self.tenant,
            campaign.id,
            "reviewer",
            "brand_reviewer",
            ApprovalDecision.APPROVED,
        )
        return self.workflow.review_plan(
            self.tenant,
            campaign.id,
            "owner",
            "campaign_owner",
            ApprovalDecision.APPROVED,
        )

    def test_full_happy_path_exports_manifest(self) -> None:
        campaign = self._to_variants()
        campaign = self.workflow.select_variant(
            self.tenant,
            campaign.id,
            "owner",
            "campaign_owner",
            campaign.variants[0].id,
            "brand_match",
            "Best brand match.",
        )
        campaign = self.workflow.review_final(
            self.tenant,
            campaign.id,
            "legal",
            "legal_reviewer",
            ApprovalDecision.APPROVED,
        )
        self.assertEqual(campaign.status, CampaignStatus.COMPLETED)
        self.assertIsNotNone(campaign.export)
        self.assertEqual(len(campaign.export.formats), 4)

    def test_plan_cannot_be_approved_before_brand_rules(self) -> None:
        with self.assertRaises(InvalidTransitionError):
            self.workflow.review_plan(
                self.tenant,
                self.campaign.id,
                "owner",
                "campaign_owner",
                ApprovalDecision.APPROVED,
            )

    def test_rejected_plan_stays_at_gate_with_new_revision(self) -> None:
        campaign = self.workflow.compile_brand_guide(self.tenant, self.campaign.id, GUIDE)
        campaign = self.workflow.review_brand_rules(
            self.tenant,
            campaign.id,
            "reviewer",
            "brand_reviewer",
            ApprovalDecision.APPROVED,
        )
        campaign = self.workflow.review_plan(
            self.tenant,
            campaign.id,
            "owner",
            "campaign_owner",
            ApprovalDecision.CHANGES_REQUESTED,
            "Make the strategy more community-led.",
        )
        self.assertEqual(campaign.status, CampaignStatus.PLAN_PENDING_APPROVAL)
        self.assertEqual(campaign.plan.revision, 2)

    def test_brand_rule_corrections_reject_unsafe_palette_values(self) -> None:
        campaign = self.workflow.compile_brand_guide(self.tenant, self.campaign.id, GUIDE)
        with self.assertRaisesRegex(ValidationError, "six-digit hex"):
            self.workflow.review_brand_rules(
                self.tenant,
                campaign.id,
                "reviewer",
                "brand_reviewer",
                ApprovalDecision.APPROVED,
                corrections={"colors": ['#112233" onload="alert(1)']},
            )

    def test_invalid_variant_selection_is_rejected(self) -> None:
        campaign = self._to_variants()
        with self.assertRaises(ValidationError):
            self.workflow.select_variant(
                self.tenant,
                campaign.id,
                "owner",
                "campaign_owner",
                "var_000000000000",
                "brand_match",
                "Wrong ID.",
            )

    def test_final_changes_regenerate_variants(self) -> None:
        campaign = self._to_variants()
        original_ids = {item.id for item in campaign.variants}
        campaign = self.workflow.select_variant(
            self.tenant,
            campaign.id,
            "owner",
            "campaign_owner",
            campaign.variants[0].id,
            "brief_match",
            "Good direction.",
        )
        campaign = self.workflow.review_final(
            self.tenant,
            campaign.id,
            "legal",
            "legal_reviewer",
            ApprovalDecision.CHANGES_REQUESTED,
            "Reduce the headline intensity.",
        )
        self.assertEqual(campaign.status, CampaignStatus.VARIANTS_PENDING_APPROVAL)
        self.assertFalse(original_ids & {item.id for item in campaign.variants})

    def test_campaign_events_form_audit_trail(self) -> None:
        campaign = self._to_variants()
        event_types = [item.event_type for item in self.workflow.events(self.tenant, campaign.id)]
        self.assertIn("brand_rules.approved", event_types)
        self.assertIn("variants.ranked", event_types)

    def test_cancelled_campaign_is_terminal(self) -> None:
        campaign = self.workflow.cancel(self.tenant, self.campaign.id, "owner")
        self.assertEqual(campaign.status, CampaignStatus.CANCELLED)
        with self.assertRaises(InvalidTransitionError):
            self.workflow.compile_brand_guide(self.tenant, campaign.id, GUIDE)

    def test_generated_variants_have_stored_images(self) -> None:
        campaign = self._to_variants()
        self.assertTrue(all(item.asset_object_key for item in campaign.variants))
        self.assertTrue(
            all(
                self.workflow.exporter.object_store.get(item.asset_object_key)
                for item in campaign.variants
            )
        )
