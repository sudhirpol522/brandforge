import unittest

from brandforge.domain import Campaign, OutboxEvent
from brandforge.integrations.sqlalchemy_repository import SQLAlchemyCampaignRepository
from tests.helpers import brief


class SQLAlchemyRepositoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repository = SQLAlchemyCampaignRepository("sqlite+pysqlite:///:memory:")

    def test_atomic_save_event_and_idempotency_round_trip(self) -> None:
        campaign = Campaign.create("tenant-a", "Campaign", brief())
        event = OutboxEvent.create("tenant-a", campaign.id, "campaign.created", {})
        saved = self.repository.save_with_event(campaign, event, 0)

        self.assertEqual(self.repository.get("tenant-a", saved.id).version, 1)
        self.assertEqual(self.repository.events("tenant-a", saved.id)[0].id, event.id)

        response: dict[str, object] = {"campaign": {"id": saved.id}}
        self.repository.idempotency_put("tenant-a", "create-key", response)
        self.repository.idempotency_put("tenant-a", "create-key", {"duplicate": True})
        self.assertEqual(
            self.repository.idempotency_get("tenant-a", "create-key"),
            response,
        )

    def test_outbox_publish_lifecycle(self) -> None:
        campaign = Campaign.create("tenant-a", "Campaign", brief())
        event = OutboxEvent.create("tenant-a", campaign.id, "campaign.created", {})
        self.repository.save_with_event(campaign, event, 0)
        self.assertEqual(self.repository.unpublished_events()[0].id, event.id)
        self.repository.mark_published(event.id, "2026-01-01T00:00:00Z")
        self.assertEqual(self.repository.unpublished_events(), [])
