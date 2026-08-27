import json
import tempfile
import unittest
from dataclasses import FrozenInstanceError
from pathlib import Path

from brandforge.domain import ApprovalDecision, CampaignStatus, DesignChannel, LayerDocument
from brandforge.exceptions import ConcurrencyError, ValidationError
from tests.helpers import GUIDE, brief, workflow


class DesignEditorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.workflow = workflow(Path(self.temp.name))
        self.tenant = "tenant-a"
        campaign = self.workflow.create_campaign(self.tenant, "Launch", brief())
        campaign = self.workflow.compile_brand_guide(self.tenant, campaign.id, GUIDE)
        campaign = self.workflow.review_brand_rules(
            self.tenant,
            campaign.id,
            "brand",
            "brand_reviewer",
            ApprovalDecision.APPROVED,
        )
        campaign = self.workflow.review_plan(
            self.tenant,
            campaign.id,
            "owner",
            "campaign_owner",
            ApprovalDecision.APPROVED,
        )
        campaign = self.workflow.select_variant(
            self.tenant,
            campaign.id,
            "owner",
            "campaign_owner",
            campaign.variants[0].id,
            "brand_match",
            "Best match.",
        )
        self.campaign = self.workflow.review_final(
            self.tenant,
            campaign.id,
            "legal",
            "legal_reviewer",
            ApprovalDecision.APPROVED,
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    @staticmethod
    def _document(channel: DesignChannel = DesignChannel.INSTAGRAM) -> LayerDocument:
        sizes = {
            DesignChannel.INSTAGRAM: (1080, 1350),
            DesignChannel.EMAIL: (1200, 600),
            DesignChannel.WEB: (1440, 560),
            DesignChannel.PRESENTATION: (1920, 1080),
        }
        width, height = sizes[channel]
        return LayerDocument(
            channel=channel,
            width=width,
            height=height,
            layers=[{"id": "headline", "type": "text", "text": "Edited"}],
        )

    @staticmethod
    def _svg(width: int = 1080, height: int = 1350, text: str = "Edited") -> str:
        return (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" '
            f'height="{height}"><text>{text}</text></svg>'
        )

    def _save(self, *, expected_revision: int = 0, text: str = "Edited"):
        return self.workflow.save_design(
            self.tenant,
            self.campaign.id,
            "instagram",
            layer_document=self._document(),
            fabric_json={"objects": [{"type": "text", "text": text}]},
            svg=self._svg(text=text),
            preview_png=b"\x89PNG\r\n\x1a\npreview",
            expected_revision=expected_revision,
            created_by="designer",
            editor_version="7.0",
        )

    def test_save_uses_immutable_versioned_object_keys(self) -> None:
        campaign = self._save()
        first = campaign.designs["instagram"][0]
        self.assertEqual(
            first.layer_document_key,
            f"designs/{self.tenant}/{campaign.id}/instagram/v1/layer-document.json",
        )
        self.assertTrue(first.fabric_json_key.endswith("/v1/fabric.json"))
        self.assertTrue(first.svg_key.endswith("/v1/design.svg"))
        self.assertTrue(first.preview_png_key.endswith("/v1/preview.png"))
        with self.assertRaises(FrozenInstanceError):
            first.revision = 2  # type: ignore[misc]

        self.campaign = campaign
        campaign = self._save(expected_revision=1, text="Second")
        self.assertEqual([item.revision for item in campaign.designs["instagram"]], [1, 2])
        stored_first = self.workflow.exporter.object_store.get(first.svg_key).decode()
        self.assertEqual(stored_first, self._svg())

    def test_stale_design_revision_is_rejected(self) -> None:
        self.campaign = self._save()
        with self.assertRaises(ConcurrencyError):
            self._save(expected_revision=0)

    def test_validation_rejects_unknown_channels_and_layer_types(self) -> None:
        with self.assertRaises(ValidationError):
            self.workflow.save_design(
                self.tenant,
                self.campaign.id,
                "../instagram",
                layer_document=self._document(),
                fabric_json={},
                svg=self._svg(),
                preview_png=None,
                expected_revision=0,
                created_by="designer",
            )
        document = self._document()
        document.layers[0]["type"] = "iframe"
        with self.assertRaises(ValidationError):
            self.workflow.save_design(
                self.tenant,
                self.campaign.id,
                "instagram",
                layer_document=document,
                fabric_json={},
                svg=self._svg(),
                preview_png=None,
                expected_revision=0,
                created_by="designer",
            )

    def test_completed_edit_invalidates_export_and_preserves_approval_audit(self) -> None:
        approval_ids = [item.id for item in self.campaign.approvals]
        campaign = self._save()

        self.assertEqual(campaign.status, CampaignStatus.FINAL_APPROVAL)
        self.assertIsNone(campaign.export)
        self.assertEqual([item.id for item in campaign.approvals], approval_ids)
        event = self.workflow.events(self.tenant, campaign.id)[-1]
        self.assertEqual(event.event_type, "design.edited")
        self.assertEqual(event.payload["revision"], 1)
        self.assertEqual(event.payload["from"], CampaignStatus.COMPLETED)
        self.assertEqual(event.payload["to"], CampaignStatus.FINAL_APPROVAL)

    def test_reapproval_exports_exact_edited_svg_and_records_provenance(self) -> None:
        edited_svg = self._svg(text="Exact &amp; approved")
        campaign = self.workflow.save_design(
            self.tenant,
            self.campaign.id,
            "instagram",
            layer_document=self._document(),
            fabric_json={"objects": []},
            svg=edited_svg,
            preview_png=None,
            expected_revision=0,
            created_by="designer",
        )
        campaign = self.workflow.review_final(
            self.tenant,
            campaign.id,
            "legal-2",
            "legal_reviewer",
            ApprovalDecision.APPROVED,
        )

        assert campaign.export is not None
        exported = self.workflow.exporter.object_store.get(
            campaign.export.formats["instagram"]
        ).decode()
        self.assertEqual(exported, edited_svg)
        self.assertNotEqual(
            self.workflow.exporter.object_store.get(campaign.export.formats["email"]).decode(),
            edited_svg,
        )
        revision = campaign.designs["instagram"][-1]
        self.assertEqual(
            campaign.export.provenance["design_revision_ids"]["instagram"], revision.id
        )
        manifest = json.loads(
            self.workflow.exporter.object_store.get(campaign.export.object_key)
        )
        self.assertEqual(
            manifest["design_sources"]["instagram"]["canonical_layer_source"],
            revision.layer_document_key,
        )
