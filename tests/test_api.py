import base64
import tempfile
import unittest
from pathlib import Path

from starlette.testclient import TestClient

from apps.api.main import create_app
from brandforge.config import Settings

GUIDE = """
Aster Run brand guide.
Colors: #182A4D, #F4B942, #FFFFFF.
Fonts: Montserrat and Inter.
Tone: energetic, premium, inclusive.
Do not use: cheap, guaranteed results.
Logo clear space: 32px.
""".strip()


def payload() -> dict[str, object]:
    return {
        "name": "Campus launch",
        "brief": {
            "product_name": "Aster Run One",
            "objective": "Launch a premium everyday running shoe.",
            "audience": "university students",
            "channels": ["instagram", "email", "web", "presentation"],
            "call_to_action": "Find your pace",
        },
        "brand_guide_text": GUIDE,
    }


class ApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.settings = Settings(
            database_url=f"sqlite:///{root / 'brandforge.db'}",
            local_object_store_path=str(root / "objects"),
            retrieval_enabled=True,
        )
        self.client = TestClient(create_app(self.settings))

    def tearDown(self) -> None:
        self.client.close()
        self.temp.cleanup()

    def test_health_and_idempotent_creation(self) -> None:
        self.assertEqual(self.client.get("/health/ready").status_code, 200)
        headers = {"X-Idempotency-Key": "same-create-request"}
        first = self.client.post("/v1/campaigns", json=payload(), headers=headers)
        second = self.client.post("/v1/campaigns", json=payload(), headers=headers)
        self.assertEqual(first.status_code, 201)
        self.assertEqual(
            first.json()["campaign"]["id"],
            second.json()["campaign"]["id"],
        )

    def test_complete_campaign_through_human_gates(self) -> None:
        campaign = self.client.post("/v1/campaigns", json=payload()).json()["campaign"]
        campaign_id = campaign["id"]

        brand = self.client.post(
            f"/v1/campaigns/{campaign_id}/approvals/brand-rules",
            json={"decision": "approved", "comments": "Rules confirmed."},
        )
        self.assertEqual(brand.json()["campaign"]["status"], "plan_pending_approval")

        plan = self.client.post(
            f"/v1/campaigns/{campaign_id}/approvals/plan",
            json={"decision": "approved", "comments": "Strategy confirmed."},
        )
        campaign = plan.json()["campaign"]
        self.assertEqual(campaign["status"], "variants_pending_approval")
        self.assertEqual(len(campaign["variants"]), 3)
        retrieval_traces = [
            trace
            for trace in campaign["agent_traces"]
            if trace.get("agent") == "multimodal_retrieval"
        ]
        self.assertEqual(len(retrieval_traces), 1)
        self.assertEqual(
            retrieval_traces[0]["tool_calls"][0]["model"],
            "deterministic-hash-non-production",
        )

        chosen = campaign["variants"][0]
        selection = self.client.post(
            f"/v1/campaigns/{campaign_id}/selection",
            json={
                "variant_id": chosen["id"],
                "reason_code": "brand_match",
                "explanation": "Best brand alignment.",
            },
        )
        self.assertEqual(selection.json()["campaign"]["status"], "final_approval")

        final = self.client.post(
            f"/v1/campaigns/{campaign_id}/approvals/final",
            json={"decision": "approved", "comments": "Legal approved."},
        )
        completed = final.json()["campaign"]
        self.assertEqual(completed["status"], "completed")

        feedback_id = completed["feedback"][0]["id"]
        curated = self.client.post(
            f"/v1/campaigns/{campaign_id}/preferences/{feedback_id}/curate",
            json={"status": "curated", "dataset_version": "reviewed-v1"},
        )
        self.assertEqual(curated.status_code, 200)
        self.assertTrue(curated.json()["campaign"]["feedback"][0]["curated"])
        dataset = self.client.get("/v1/preference-datasets/reviewed-v1")
        self.assertEqual(dataset.status_code, 200)
        self.assertEqual(dataset.json()["row_count"], 2)
        imported = self.client.post(
            "/v1/preference-datasets/import",
            json={
                "dataset_version": "reviewed-v1",
                "rows": dataset.json()["rows"],
            },
        )
        self.assertEqual(imported.status_code, 200)
        self.assertEqual(imported.json()["fingerprint"], dataset.json()["fingerprint"])

        backfill = self.client.post(f"/v1/campaigns/{campaign_id}/retrieval/backfill")
        self.assertEqual(backfill.status_code, 200, backfill.text)
        self.assertEqual(backfill.json()["summaries"][0]["indexed"], 2)
        retrieval_status = self.client.get(
            f"/v1/campaigns/{campaign_id}/retrieval/status"
        )
        self.assertEqual(retrieval_status.json()["ready"], 2)
        search = self.client.post(
            f"/v1/campaigns/{campaign_id}/retrieval/text",
            json={"query": "premium running campaign", "limit": 5},
        )
        self.assertEqual(search.status_code, 200)
        self.assertTrue(search.json()["synthetic"])
        self.assertGreaterEqual(len(search.json()["results"]), 1)

        image = self.client.get(f"/v1/campaigns/{campaign_id}/variants/{chosen['id']}/image")
        query_png = base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
        )
        image_search = self.client.post(
            f"/v1/campaigns/{campaign_id}/retrieval/image",
            files={"file": ("query.png", query_png, "image/png")},
            data={"limit": "5"},
        )
        self.assertEqual(image_search.status_code, 200, image_search.text)
        self.assertGreaterEqual(len(image_search.json()["results"]), 1)
        svg = self.client.get(f"/v1/campaigns/{campaign_id}/exports/instagram")
        manifest = self.client.get(f"/v1/campaigns/{campaign_id}/exports/manifest")
        events = self.client.get(f"/v1/campaigns/{campaign_id}/events")
        self.assertEqual(image.status_code, 200)
        self.assertEqual(svg.headers["content-type"], "image/svg+xml")
        self.assertEqual(manifest.json()["campaign_id"], campaign_id)
        self.assertGreaterEqual(len(events.json()["events"]), 8)

    def test_tenant_isolation_returns_not_found(self) -> None:
        campaign_id = self.client.post("/v1/campaigns", json=payload()).json()["campaign"]["id"]
        response = self.client.get(
            f"/v1/campaigns/{campaign_id}",
            headers={"X-Tenant-ID": "different-studio"},
        )
        self.assertEqual(response.status_code, 404)

    def test_production_mode_requires_validated_identity(self) -> None:
        self.client.close()
        self.client = TestClient(
            create_app(
                self.settings.__class__(
                    **{
                        field: getattr(self.settings, field)
                        for field in self.settings.__dataclass_fields__
                        if field != "dev_auth"
                    },
                    dev_auth=False,
                )
            )
        )
        response = self.client.get("/v1/campaigns")
        self.assertEqual(response.status_code, 401)
