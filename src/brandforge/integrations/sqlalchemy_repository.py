from __future__ import annotations

import builtins
import json
from typing import Any

from sqlalchemy import (
    JSON,
    Column,
    DateTime,
    Integer,
    MetaData,
    String,
    Table,
    create_engine,
    func,
    select,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.exc import IntegrityError

from ..domain import Campaign, OutboxEvent
from ..exceptions import ConcurrencyError, NotFoundError


class SQLAlchemyCampaignRepository:
    """PostgreSQL repository; tenant predicates are included in every read."""

    def __init__(self, database_url: str) -> None:
        self.engine = create_engine(database_url, pool_pre_ping=True, pool_recycle=300)
        metadata = MetaData()
        json_type: Any = JSON().with_variant(JSONB(), "postgresql")
        self.campaigns = Table(
            "campaigns",
            metadata,
            # IDs remain opaque strings so exports and traces are stable across stores.
            Column("id", String(64), primary_key=True),
            Column("tenant_id", String(64), nullable=False, index=True),
            Column("version", Integer, nullable=False),
            Column("data", json_type, nullable=False),
            Column(
                "updated_at", DateTime(timezone=True), server_default=func.now(), nullable=False
            ),
        )
        self.outbox = Table(
            "outbox",
            metadata,
            Column("id", String(64), primary_key=True),
            Column("tenant_id", String(64), nullable=False, index=True),
            Column("aggregate_id", String(64), nullable=False, index=True),
            Column("event_type", String(128), nullable=False),
            Column("payload", json_type, nullable=False),
            Column("occurred_at", String(64), nullable=False),
            Column("published_at", String(64)),
        )
        self.idempotency = Table(
            "idempotency",
            metadata,
            Column("tenant_id", String(64), primary_key=True),
            Column("idempotency_key", String(160), primary_key=True),
            Column("response", json_type, nullable=False),
            Column(
                "created_at", DateTime(timezone=True), server_default=func.now(), nullable=False
            ),
        )
        metadata.create_all(self.engine)

    def save(self, campaign: Campaign, expected_version: int | None) -> Campaign:
        with self.engine.begin() as connection:
            self._set_tenant(connection, campaign.tenant_id)
            saved = self._save_in_transaction(connection, campaign, expected_version)
        return saved

    def save_with_event(
        self,
        campaign: Campaign,
        event: OutboxEvent,
        expected_version: int | None,
    ) -> Campaign:
        """Atomically persist campaign state and its outbox event."""
        with self.engine.begin() as connection:
            self._set_tenant(connection, campaign.tenant_id)
            saved = self._save_in_transaction(connection, campaign, expected_version)
            connection.execute(
                self.outbox.insert().values(
                    id=event.id,
                    tenant_id=event.tenant_id,
                    aggregate_id=event.aggregate_id,
                    event_type=event.event_type,
                    payload=event.payload,
                    occurred_at=event.occurred_at,
                    published_at=event.published_at,
                )
            )
        return saved

    def _save_in_transaction(
        self,
        connection: Any,
        campaign: Campaign,
        expected_version: int | None,
    ) -> Campaign:
        row = connection.execute(
            select(self.campaigns.c.version)
            .where(self.campaigns.c.id == campaign.id)
            .with_for_update()
        ).first()
        current_version = int(row.version) if row else 0
        if expected_version is not None and current_version != expected_version:
            raise ConcurrencyError(
                f"campaign {campaign.id} expected version {expected_version}, "
                f"found {current_version}"
            )
        campaign.version = current_version + 1
        data = campaign.to_dict()
        if row:
            connection.execute(
                self.campaigns.update()
                .where(self.campaigns.c.id == campaign.id)
                .values(
                    tenant_id=campaign.tenant_id,
                    version=campaign.version,
                    data=data,
                    updated_at=func.now(),
                )
            )
        else:
            connection.execute(
                self.campaigns.insert().values(
                    id=campaign.id,
                    tenant_id=campaign.tenant_id,
                    version=campaign.version,
                    data=data,
                )
            )
        return Campaign.from_dict(campaign.to_dict())

    def get(self, tenant_id: str, campaign_id: str) -> Campaign:
        with self.engine.connect() as connection:
            self._set_tenant(connection, tenant_id)
            row = connection.execute(
                select(self.campaigns.c.data).where(
                    self.campaigns.c.id == campaign_id,
                    self.campaigns.c.tenant_id == tenant_id,
                )
            ).first()
        if row is None:
            raise NotFoundError(f"campaign {campaign_id} not found")
        raw = row.data if isinstance(row.data, dict) else json.loads(row.data)
        return Campaign.from_dict(raw)

    def list(self, tenant_id: str) -> list[Campaign]:
        with self.engine.connect() as connection:
            self._set_tenant(connection, tenant_id)
            rows = connection.execute(
                select(self.campaigns.c.data)
                .where(self.campaigns.c.tenant_id == tenant_id)
                .order_by(self.campaigns.c.updated_at.desc())
            ).all()
        return [
            Campaign.from_dict(row.data if isinstance(row.data, dict) else json.loads(row.data))
            for row in rows
        ]

    def emit(self, event: OutboxEvent) -> None:
        try:
            with self.engine.begin() as connection:
                self._set_tenant(connection, event.tenant_id)
                connection.execute(
                    self.outbox.insert().values(
                        id=event.id,
                        tenant_id=event.tenant_id,
                        aggregate_id=event.aggregate_id,
                        event_type=event.event_type,
                        payload=event.payload,
                        occurred_at=event.occurred_at,
                        published_at=event.published_at,
                    )
                )
        except IntegrityError:
            return

    def events(self, tenant_id: str, campaign_id: str) -> builtins.list[OutboxEvent]:
        with self.engine.connect() as connection:
            self._set_tenant(connection, tenant_id)
            rows = (
                connection.execute(
                    select(self.outbox)
                    .where(
                        self.outbox.c.tenant_id == tenant_id,
                        self.outbox.c.aggregate_id == campaign_id,
                    )
                    .order_by(self.outbox.c.occurred_at)
                )
                .mappings()
                .all()
            )
        return [OutboxEvent(**dict(row)) for row in rows]

    def unpublished_events(self, limit: int = 100) -> builtins.list[OutboxEvent]:
        with self.engine.connect() as connection:
            rows = (
                connection.execute(
                    select(self.outbox)
                    .where(self.outbox.c.published_at.is_(None))
                    .order_by(self.outbox.c.occurred_at)
                    .limit(max(1, min(limit, 1000)))
                )
                .mappings()
                .all()
            )
        return [OutboxEvent(**dict(row)) for row in rows]

    def mark_published(self, event_id: str, published_at: str) -> None:
        with self.engine.begin() as connection:
            connection.execute(
                self.outbox.update()
                .where(self.outbox.c.id == event_id, self.outbox.c.published_at.is_(None))
                .values(published_at=published_at)
            )

    def idempotency_get(self, tenant_id: str, key: str) -> dict[str, object] | None:
        with self.engine.connect() as connection:
            self._set_tenant(connection, tenant_id)
            row = connection.execute(
                select(self.idempotency.c.response).where(
                    self.idempotency.c.tenant_id == tenant_id,
                    self.idempotency.c.idempotency_key == key,
                )
            ).first()
        if row is None:
            return None
        value = row.response if isinstance(row.response, dict) else json.loads(row.response)
        return dict(value)

    def idempotency_put(
        self,
        tenant_id: str,
        key: str,
        response: dict[str, object],
    ) -> None:
        try:
            with self.engine.begin() as connection:
                self._set_tenant(connection, tenant_id)
                connection.execute(
                    self.idempotency.insert().values(
                        tenant_id=tenant_id,
                        idempotency_key=key,
                        response=response,
                    )
                )
        except IntegrityError:
            return

    def _set_tenant(self, connection: Any, tenant_id: str) -> None:
        if self.engine.dialect.name == "postgresql":
            connection.execute(
                text("SELECT set_config('app.tenant_id', :tenant_id, true)"),
                {"tenant_id": tenant_id},
            )
