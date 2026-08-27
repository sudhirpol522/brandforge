from __future__ import annotations

import builtins
import copy
import json
import sqlite3
import threading
from pathlib import Path

from .domain import Campaign, OutboxEvent
from .exceptions import ConcurrencyError, NotFoundError, TenantIsolationError


class InMemoryCampaignRepository:
    def __init__(self) -> None:
        self._campaigns: dict[str, Campaign] = {}
        self._events: list[OutboxEvent] = []
        self._lock = threading.RLock()

    def save(self, campaign: Campaign, expected_version: int | None) -> Campaign:
        with self._lock:
            current = self._campaigns.get(campaign.id)
            current_version = current.version if current else 0
            if expected_version is not None and expected_version != current_version:
                raise ConcurrencyError(
                    f"campaign {campaign.id} expected version {expected_version}, "
                    f"found {current_version}"
                )
            campaign.version = current_version + 1
            self._campaigns[campaign.id] = copy.deepcopy(campaign)
            return copy.deepcopy(campaign)

    def save_with_event(
        self,
        campaign: Campaign,
        event: OutboxEvent,
        expected_version: int | None,
    ) -> Campaign:
        with self._lock:
            saved = self.save(campaign, expected_version)
            self._events.append(copy.deepcopy(event))
            return saved

    def get(self, tenant_id: str, campaign_id: str) -> Campaign:
        with self._lock:
            campaign = self._campaigns.get(campaign_id)
            if campaign is None:
                raise NotFoundError(f"campaign {campaign_id} not found")
            if campaign.tenant_id != tenant_id:
                raise TenantIsolationError("campaign is not available to this tenant")
            return copy.deepcopy(campaign)

    def list(self, tenant_id: str) -> list[Campaign]:
        with self._lock:
            values = [item for item in self._campaigns.values() if item.tenant_id == tenant_id]
            return [
                copy.deepcopy(item) for item in sorted(values, key=lambda value: value.created_at)
            ]

    def emit(self, event: OutboxEvent) -> None:
        with self._lock:
            self._events.append(copy.deepcopy(event))

    def events(self, tenant_id: str, campaign_id: str) -> builtins.list[OutboxEvent]:
        with self._lock:
            return [
                copy.deepcopy(item)
                for item in self._events
                if item.tenant_id == tenant_id and item.aggregate_id == campaign_id
            ]


class SQLiteCampaignRepository:
    """Durable single-node repository used by the zero-configuration local demo."""

    def __init__(self, database_path: str | Path) -> None:
        self.path = Path(database_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS campaigns (
                    id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    data TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_campaigns_tenant
                    ON campaigns (tenant_id, updated_at);
                CREATE TABLE IF NOT EXISTS outbox (
                    id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    aggregate_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    occurred_at TEXT NOT NULL,
                    published_at TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_outbox_aggregate
                    ON outbox (tenant_id, aggregate_id, occurred_at);
                CREATE TABLE IF NOT EXISTS idempotency (
                    tenant_id TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL,
                    response TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (tenant_id, idempotency_key)
                );
                """
            )

    def save(self, campaign: Campaign, expected_version: int | None) -> Campaign:
        with self._lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            return self._save_in_transaction(connection, campaign, expected_version)

    def save_with_event(
        self,
        campaign: Campaign,
        event: OutboxEvent,
        expected_version: int | None,
    ) -> Campaign:
        """Persist aggregate state and its domain event in one SQLite transaction."""
        with self._lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            saved = self._save_in_transaction(connection, campaign, expected_version)
            self._emit_in_transaction(connection, event)
            return saved

    def _save_in_transaction(
        self,
        connection: sqlite3.Connection,
        campaign: Campaign,
        expected_version: int | None,
    ) -> Campaign:
        row = connection.execute(
            "SELECT version FROM campaigns WHERE id = ?", (campaign.id,)
        ).fetchone()
        current_version = int(row["version"]) if row else 0
        if expected_version is not None and expected_version != current_version:
            raise ConcurrencyError(
                f"campaign {campaign.id} expected version {expected_version}, "
                f"found {current_version}"
            )
        campaign.version = current_version + 1
        payload = json.dumps(campaign.to_dict(), separators=(",", ":"), sort_keys=True)
        connection.execute(
            """
            INSERT INTO campaigns (id, tenant_id, version, data, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                tenant_id = excluded.tenant_id,
                version = excluded.version,
                data = excluded.data,
                updated_at = excluded.updated_at
            """,
            (campaign.id, campaign.tenant_id, campaign.version, payload, campaign.updated_at),
        )
        return Campaign.from_dict(campaign.to_dict())

    def get(self, tenant_id: str, campaign_id: str) -> Campaign:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT tenant_id, data FROM campaigns WHERE id = ?", (campaign_id,)
            ).fetchone()
        if row is None:
            raise NotFoundError(f"campaign {campaign_id} not found")
        if row["tenant_id"] != tenant_id:
            raise TenantIsolationError("campaign is not available to this tenant")
        return Campaign.from_dict(json.loads(row["data"]))

    def list(self, tenant_id: str) -> list[Campaign]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT data FROM campaigns WHERE tenant_id = ? ORDER BY updated_at DESC",
                (tenant_id,),
            ).fetchall()
        return [Campaign.from_dict(json.loads(row["data"])) for row in rows]

    def emit(self, event: OutboxEvent) -> None:
        with self._connect() as connection:
            self._emit_in_transaction(connection, event)

    @staticmethod
    def _emit_in_transaction(connection: sqlite3.Connection, event: OutboxEvent) -> None:
        connection.execute(
            """
            INSERT OR IGNORE INTO outbox
                (id, tenant_id, aggregate_id, event_type, payload, occurred_at, published_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event.id,
                event.tenant_id,
                event.aggregate_id,
                event.event_type,
                json.dumps(event.payload, separators=(",", ":"), sort_keys=True),
                event.occurred_at,
                event.published_at,
            ),
        )

    def events(self, tenant_id: str, campaign_id: str) -> builtins.list[OutboxEvent]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM outbox
                WHERE tenant_id = ? AND aggregate_id = ?
                ORDER BY occurred_at ASC, id ASC
                """,
                (tenant_id, campaign_id),
            ).fetchall()
        return [
            OutboxEvent(
                id=row["id"],
                tenant_id=row["tenant_id"],
                aggregate_id=row["aggregate_id"],
                event_type=row["event_type"],
                payload=json.loads(row["payload"]),
                occurred_at=row["occurred_at"],
                published_at=row["published_at"],
            )
            for row in rows
        ]

    def unpublished_events(self, limit: int = 100) -> builtins.list[OutboxEvent]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM outbox WHERE published_at IS NULL ORDER BY occurred_at LIMIT ?",
                (max(1, min(limit, 1000)),),
            ).fetchall()
        return [
            OutboxEvent(
                id=row["id"],
                tenant_id=row["tenant_id"],
                aggregate_id=row["aggregate_id"],
                event_type=row["event_type"],
                payload=json.loads(row["payload"]),
                occurred_at=row["occurred_at"],
                published_at=row["published_at"],
            )
            for row in rows
        ]

    def mark_published(self, event_id: str, published_at: str) -> None:
        with self._connect() as connection:
            connection.execute(
                "UPDATE outbox SET published_at = ? WHERE id = ? AND published_at IS NULL",
                (published_at, event_id),
            )

    def idempotency_get(self, tenant_id: str, key: str) -> dict[str, object] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT response FROM idempotency WHERE tenant_id = ? AND idempotency_key = ?",
                (tenant_id, key),
            ).fetchone()
        return json.loads(row["response"]) if row else None

    def idempotency_put(self, tenant_id: str, key: str, response: dict[str, object]) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT OR IGNORE INTO idempotency (tenant_id, idempotency_key, response)
                VALUES (?, ?, ?)
                """,
                (tenant_id, key, json.dumps(response, separators=(",", ":"), sort_keys=True)),
            )
