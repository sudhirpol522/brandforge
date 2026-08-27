import tempfile
import unittest
from pathlib import Path

from brandforge.domain import Campaign, DesignChannel, DesignRevision, OutboxEvent
from brandforge.exceptions import ConcurrencyError, TenantIsolationError
from brandforge.persistence import InMemoryCampaignRepository, SQLiteCampaignRepository
from tests.helpers import brief


class PersistenceTests(unittest.TestCase):
    def test_round_trip_nested_campaign(self) -> None:
        campaign = Campaign.create("tenant-a", "Test", brief())
        campaign.designs["instagram"] = [
            DesignRevision(
                id="dsn_1",
                channel=DesignChannel.INSTAGRAM,
                revision=1,
                layer_document_key="designs/tenant-a/cmp/instagram/v1/layer-document.json",
                fabric_json_key="designs/tenant-a/cmp/instagram/v1/fabric.json",
                svg_key="designs/tenant-a/cmp/instagram/v1/design.svg",
                preview_png_key=None,
                editor="fabric",
                editor_version="7",
                created_by="designer",
                created_at="2026-08-27T00:00:00+00:00",
                hashes={"svg": "abc"},
            )
        ]
        decoded = Campaign.from_dict(campaign.to_dict())
        self.assertEqual(decoded.brief.product_name, campaign.brief.product_name)
        self.assertEqual(decoded.status, campaign.status)
        self.assertEqual(decoded.designs["instagram"][0], campaign.designs["instagram"][0])

    def test_old_campaign_payload_without_designs_remains_compatible(self) -> None:
        campaign = Campaign.create("tenant-a", "Test", brief())
        payload = campaign.to_dict()
        payload.pop("designs")
        self.assertEqual(Campaign.from_dict(payload).designs, {})

    def test_optimistic_concurrency_rejects_stale_write(self) -> None:
        repository = InMemoryCampaignRepository()
        saved = repository.save(Campaign.create("tenant-a", "Test", brief()), 0)
        stale = repository.get("tenant-a", saved.id)
        repository.save(saved, saved.version)
        with self.assertRaises(ConcurrencyError):
            repository.save(stale, stale.version)

    def test_cross_tenant_lookup_is_rejected(self) -> None:
        repository = InMemoryCampaignRepository()
        saved = repository.save(Campaign.create("tenant-a", "Test", brief()), 0)
        with self.assertRaises(TenantIsolationError):
            repository.get("tenant-b", saved.id)

    def test_sqlite_persists_between_instances(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "brandforge.db"
            first = SQLiteCampaignRepository(path)
            saved = first.save(Campaign.create("tenant-a", "Test", brief()), 0)
            second = SQLiteCampaignRepository(path)
            self.assertEqual(second.get("tenant-a", saved.id).id, saved.id)

    def test_in_memory_list_and_event_filters_are_tenant_scoped(self) -> None:
        repository = InMemoryCampaignRepository()
        first = repository.save(Campaign.create("tenant-a", "A", brief()), 0)
        repository.save(Campaign.create("tenant-b", "B", brief()), 0)
        event = OutboxEvent.create("tenant-a", first.id, "campaign.created", {})
        repository.emit(event)

        self.assertEqual([item.id for item in repository.list("tenant-a")], [first.id])
        self.assertEqual(repository.events("tenant-a", first.id)[0].id, event.id)

    def test_outbox_event_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = SQLiteCampaignRepository(Path(directory) / "brandforge.db")
            campaign = repository.save(Campaign.create("tenant-a", "Test", brief()), 0)
            event = OutboxEvent.create("tenant-a", campaign.id, "campaign.created", {})
            repository.emit(event)
            self.assertEqual(repository.events("tenant-a", campaign.id)[0].id, event.id)

    def test_sqlite_save_and_event_are_persisted_together(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = SQLiteCampaignRepository(Path(directory) / "brandforge.db")
            campaign = Campaign.create("tenant-a", "Test", brief())
            event = OutboxEvent.create("tenant-a", campaign.id, "campaign.created", {})
            saved = repository.save_with_event(campaign, event, 0)

            self.assertEqual(repository.get("tenant-a", saved.id).version, 1)
            self.assertEqual(repository.events("tenant-a", saved.id)[0].id, event.id)

    def test_atomic_outbox_rejects_event_when_campaign_write_is_stale(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = SQLiteCampaignRepository(Path(directory) / "brandforge.db")
            campaign = repository.save(Campaign.create("tenant-a", "Test", brief()), 0)
            event = OutboxEvent.create("tenant-a", campaign.id, "should.not.persist", {})

            with self.assertRaises(ConcurrencyError):
                repository.save_with_event(campaign, event, 0)

            self.assertEqual(repository.events("tenant-a", campaign.id), [])
