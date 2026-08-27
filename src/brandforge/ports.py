from __future__ import annotations

import builtins
from typing import Any, Protocol

from .domain import Campaign, OutboxEvent
from .retrieval import (
    EmbeddingResult,
    IndexedMultimodalRecord,
    RetrievalStatus,
    SearchRequest,
    SearchResult,
)


class CampaignRepository(Protocol):
    def save(self, campaign: Campaign, expected_version: int | None) -> Campaign: ...

    def save_with_event(
        self,
        campaign: Campaign,
        event: OutboxEvent,
        expected_version: int | None,
    ) -> Campaign: ...

    def get(self, tenant_id: str, campaign_id: str) -> Campaign: ...

    def list(self, tenant_id: str) -> list[Campaign]: ...

    def emit(self, event: OutboxEvent) -> None: ...

    def events(self, tenant_id: str, campaign_id: str) -> builtins.list[OutboxEvent]: ...


class ObjectStore(Protocol):
    def put(self, key: str, content: bytes, media_type: str) -> str: ...

    def get(self, key: str) -> bytes: ...


class CreativeProvider(Protocol):
    name: str

    def generate_text(self, *, purpose: str, prompt: str, seed: int) -> str: ...

    def generate_image(
        self, *, prompt: str, width: int, height: int, seed: int
    ) -> dict[str, Any]: ...


class EmbeddingProvider(Protocol):
    @property
    def model_name(self) -> str: ...

    @property
    def model_version(self) -> str: ...

    @property
    def dimension(self) -> int: ...

    def embed_text(self, text: str) -> EmbeddingResult: ...

    def embed_image(self, image_bytes: bytes) -> EmbeddingResult: ...


class RetrievalRepository(Protocol):
    def upsert(self, record: IndexedMultimodalRecord) -> IndexedMultimodalRecord: ...

    def get(self, tenant_id: str, record_id: str) -> IndexedMultimodalRecord: ...

    def list(
        self,
        tenant_id: str,
        *,
        status: RetrievalStatus | None = None,
        limit: int = 100,
        campaign_id: str | None = None,
        embedding_model: str | None = None,
        embedding_model_version: str | None = None,
    ) -> list[IndexedMultimodalRecord]: ...

    def search(self, request: SearchRequest) -> builtins.list[SearchResult]: ...

    def set_status(
        self,
        tenant_id: str,
        record_id: str,
        status: RetrievalStatus,
    ) -> None: ...

    def delete(self, tenant_id: str, record_id: str) -> bool: ...
