import base64
import tempfile
import unittest
from pathlib import Path

from starlette.testclient import TestClient

from apps.api.main import create_app
from brandforge.config import Settings
from brandforge.editor import MAX_PREVIEW_BYTES

GUIDE = """
Aster Run brand guide.
Colors: #182A4D, #F4B942, #FFFFFF.
Fonts: Montserrat and Inter.
Tone: energetic, premium, inclusive.
Do not use: cheap, guaranteed results.
Logo clear space: 32px.
""".strip()


class EditorApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        settings = Settings(
            database_url=f"sqlite:///{root / 'brandforge.db'}",
            local_object_store_path=str(root / "objects"),
        )
        self.client = TestClient(create_app(settings))
        self.campaign = self._complete_campaign()
        self.campaign_id = self.campaign["id"]

    def tearDown(self) -> None:
        self.client.close()
        self.temp.cleanup()

    def _complete_campaign(self) -> dict[str, object]:
        campaign = self.client.post(
            "/v1/campaigns",
            json={
                "name": "Campus launch",
                "brief": {
                    "product_name": "Aster Run One",
                    "objective": "Launch a premium everyday running shoe.",
                    "audience": "university students",
                    "channels": ["instagram", "email", "web", "presentation"],
                    "call_to_action": "Find your pace",
                },
                "brand_guide_text": GUIDE,
            },
        ).json()["campaign"]
        campaign_id = campaign["id"]
        self.client.post(
            f"/v1/campaigns/{campaign_id}/approvals/brand-rules",
            json={"decision": "approved"},
        )
        variants = self.client.post(
            f"/v1/campaigns/{campaign_id}/approvals/plan",
            json={"decision": "approved"},
        ).json()["campaign"]["variants"]
        self.client.post(
            f"/v1/campaigns/{campaign_id}/selection",
            json={
                "variant_id": variants[0]["id"],
                "reason_code": "brand_match",
                "explanation": "Best brand alignment.",
            },
        )
        return self.client.post(
            f"/v1/campaigns/{campaign_id}/approvals/final",
            json={"decision": "approved"},
        ).json()["campaign"]

    @staticmethod
    def _save_payload(
        *,
        expected_revision: int = 0,
        text: str = "Edited",
        preview: bytes | None = b"\x89PNG\r\n\x1a\npreview",
    ) -> dict[str, object]:
        return {
            "channel": "instagram",
            "layer_document": {
                "schema_version": 1,
                "channel": "instagram",
                "width": 1080,
                "height": 1350,
                "layers": [{"id": "headline", "type": "text", "text": text}],
            },
            "fabric_json": {"objects": [{"type": "text", "text": text}]},
            "svg": (
                '<svg xmlns="http://www.w3.org/2000/svg" width="1080" '
                f'height="1350"><text>{text}</text></svg>'
            ),
            "preview_png_base64": (
                base64.b64encode(preview).decode() if preview is not None else None
            ),
            "expected_revision": expected_revision,
            "editor_version": "7.0",
        }

    def test_bootstrap_get_returns_exported_svg_and_revision_zero(self) -> None:
        response = self.client.get(
            f"/v1/campaigns/{self.campaign_id}/designs/instagram"
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["revision"], 0)
        self.assertIsNone(body["revision_metadata"])
        self.assertEqual(body["layer_document"]["channel"], "instagram")
        self.assertIn("<svg", body["svg"])
        self.assertEqual(body["campaign_version"], self.campaign["version"])

    def test_put_get_and_preview_round_trip(self) -> None:
        saved = self.client.put(
            f"/v1/campaigns/{self.campaign_id}/designs/instagram",
            json=self._save_payload(),
        )

        self.assertEqual(saved.status_code, 200)
        body = saved.json()
        self.assertEqual(body["revision"], 1)
        self.assertEqual(body["revision_metadata"]["editor"], "fabric")
        self.assertEqual(body["revision_metadata"]["created_by"], "creative-director")
        self.assertEqual(body["campaign"]["status"], "final_approval")
        loaded = self.client.get(
            f"/v1/campaigns/{self.campaign_id}/designs/instagram"
        ).json()
        self.assertEqual(loaded["fabric_json"], body["fabric_json"])
        self.assertEqual(loaded["svg"], body["svg"])

        preview = self.client.get(
            f"/v1/campaigns/{self.campaign_id}/designs/instagram/preview"
        )
        self.assertEqual(preview.status_code, 200)
        self.assertEqual(preview.content, b"\x89PNG\r\n\x1a\npreview")
        self.assertEqual(preview.headers["cache-control"], "private, no-store")

    def test_revisions_are_immutable_and_stale_writes_conflict(self) -> None:
        first = self.client.put(
            f"/v1/campaigns/{self.campaign_id}/designs/instagram",
            json=self._save_payload(),
        ).json()
        stale = self.client.put(
            f"/v1/campaigns/{self.campaign_id}/designs/instagram",
            json=self._save_payload(),
        )
        self.assertEqual(stale.status_code, 409)

        second = self.client.put(
            f"/v1/campaigns/{self.campaign_id}/designs/instagram",
            json=self._save_payload(expected_revision=1, text="Second"),
        ).json()
        first_key = first["revision_metadata"]["svg_key"]
        second_key = second["revision_metadata"]["svg_key"]
        self.assertIn("/v1/design.svg", first_key)
        self.assertIn("/v2/design.svg", second_key)
        self.assertNotEqual(first_key, second_key)

    def test_invalid_preview_data_is_rejected(self) -> None:
        bad_base64 = self._save_payload()
        bad_base64["preview_png_base64"] = "%%%not-base64%%%"
        response = self.client.put(
            f"/v1/campaigns/{self.campaign_id}/designs/instagram",
            json=bad_base64,
        )
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["error"], "ValidationError")

        oversized = self._save_payload(preview=b"\x89PNG\r\n\x1a\n" + b"x" * MAX_PREVIEW_BYTES)
        response = self.client.put(
            f"/v1/campaigns/{self.campaign_id}/designs/instagram",
            json=oversized,
        )
        self.assertEqual(response.status_code, 422)

    def test_channel_validation_and_missing_preview(self) -> None:
        unsupported = self.client.get(
            f"/v1/campaigns/{self.campaign_id}/designs/tiktok"
        )
        self.assertEqual(unsupported.status_code, 422)
        mismatch = self._save_payload()
        mismatch["channel"] = "email"
        response = self.client.put(
            f"/v1/campaigns/{self.campaign_id}/designs/instagram",
            json=mismatch,
        )
        self.assertEqual(response.status_code, 422)
        preview = self.client.get(
            f"/v1/campaigns/{self.campaign_id}/designs/email/preview"
        )
        self.assertEqual(preview.status_code, 404)

    def test_design_routes_are_tenant_isolated(self) -> None:
        headers = {"X-Tenant-ID": "different-studio"}
        get_response = self.client.get(
            f"/v1/campaigns/{self.campaign_id}/designs/instagram",
            headers=headers,
        )
        put_response = self.client.put(
            f"/v1/campaigns/{self.campaign_id}/designs/instagram",
            json=self._save_payload(),
            headers=headers,
        )
        self.assertEqual(get_response.status_code, 404)
        self.assertEqual(put_response.status_code, 404)
