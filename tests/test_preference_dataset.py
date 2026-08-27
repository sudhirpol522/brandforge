import tempfile
import unittest
from pathlib import Path

from brandforge.domain import ApprovalDecision
from brandforge.preference_dataset import build_comparisons, grouped_split
from tests.helpers import GUIDE, brief, workflow


class PreferenceDatasetTests(unittest.TestCase):
    def test_selection_freezes_features_and_requires_explicit_curation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            service = workflow(Path(directory))
            campaign = service.create_campaign("tenant-a", "Campaign", brief())
            campaign = service.compile_brand_guide("tenant-a", campaign.id, GUIDE)
            campaign = service.review_brand_rules(
                "tenant-a",
                campaign.id,
                "reviewer",
                "campaign_owner",
                ApprovalDecision.APPROVED,
            )
            campaign = service.review_plan(
                "tenant-a",
                campaign.id,
                "reviewer",
                "campaign_owner",
                ApprovalDecision.APPROVED,
            )
            selected = campaign.variants[0]
            campaign = service.select_variant(
                "tenant-a",
                campaign.id,
                "reviewer",
                "campaign_owner",
                selected.id,
                "brand_match",
                "Best approved direction",
            )
            feedback = campaign.feedback[0]
            self.assertEqual(len(feedback.preferred_features), 7)
            self.assertEqual(len(feedback.rejected_features), 2)
            self.assertEqual(build_comparisons(campaign), [])
            campaign = service.curate_preference_feedback(
                "tenant-a",
                campaign.id,
                feedback.id,
                curator_id="curator",
                curation_status="curated",
                dataset_version="human-v1",
            )
            rows = build_comparisons(campaign)
            self.assertEqual(len(rows), 2)
            splits = grouped_split(rows)
            splits.assert_no_leakage()


if __name__ == "__main__":
    unittest.main()
