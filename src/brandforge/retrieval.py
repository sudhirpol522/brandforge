from __future__ import annotations

import math
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import TypeAlias
from uuid import uuid4

MetadataValue: TypeAlias = str | int | float | bool | None
Metadata: TypeAlias = Mapping[str, MetadataValue]
Embedding: TypeAlias = tuple[float, ...]


class Modality(StrEnum):
    TEXT = "text"
    IMAGE = "image"


class RetrievalStatus(StrEnum):
    PENDING = "pending"
    READY = "ready"
    FAILED = "failed"
    QUARANTINED = "quarantined"


class ApprovalStatus(StrEnum):
    APPROVED = "approved"
    UNAPPROVED = "unapproved"


class PolicyStatus(StrEnum):
    ALLOWED = "allowed"
    BLOCKED = "blocked"
    QUARANTINED = "quarantined"


class AssetKind(StrEnum):
    APPROVED_IMAGE = "approved_image"
    PRODUCT_ASSET = "product_asset"
    APPROVED_EXAMPLE = "approved_example"
    PDF_CHUNK = "pdf_chunk"
    CAMPAIGN_COPY = "campaign_copy"
    CAMPAIGN_VISUAL = "campaign_visual"


_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:@-]{0,159}$")
_SAFE_OBJECT_KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/@+-]{0,1023}$")
_SHA256 = re.compile(r"^[a-f0-9]{64}$")


def _require_text(name: str, value: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")


def _require_safe_id(name: str, value: str) -> None:
    _require_text(name, value)
    if not _SAFE_ID.fullmatch(value):
        raise ValueError(f"{name} contains unsupported characters")


def _require_object_key(value: str) -> None:
    if not _SAFE_OBJECT_KEY.fullmatch(value) or ".." in value.split("/"):
        raise ValueError("object_key contains unsupported path segments")


def _validate_metadata(values: Metadata, *, name: str) -> dict[str, MetadataValue]:
    if not isinstance(values, Mapping):
        raise ValueError(f"{name} must be a mapping")
    if len(values) > 50:
        raise ValueError(f"{name} cannot contain more than 50 entries")
    result: dict[str, MetadataValue] = {}
    for key, value in values.items():
        _require_text(f"{name} key", key)
        if len(key) > 100:
            raise ValueError(f"{name} key exceeds 100 characters")
        if not isinstance(value, (str, int, float, bool, type(None))):
            raise ValueError(f"{name}[{key!r}] must be a JSON scalar")
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError(f"{name}[{key!r}] must be finite")
        if isinstance(value, str) and len(value) > 1_000:
            raise ValueError(f"{name}[{key!r}] exceeds 1000 characters")
        result[key] = value
    return result


def validate_embedding(vector: tuple[float, ...], *, dimension: int | None = None) -> Embedding:
    if not isinstance(vector, tuple) or not vector:
        raise ValueError("embedding must be a non-empty tuple")
    if dimension is not None and (dimension < 1 or len(vector) != dimension):
        raise ValueError(f"embedding dimension must be {dimension}, got {len(vector)}")
    validated: list[float] = []
    for value in vector:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("embedding values must be real numbers")
        number = float(value)
        if not math.isfinite(number):
            raise ValueError("embedding values must be finite")
        validated.append(number)
    return tuple(validated)


def normalize_embedding(vector: tuple[float, ...]) -> Embedding:
    validated = validate_embedding(vector)
    magnitude = math.sqrt(math.fsum(value * value for value in validated))
    if magnitude <= 0.0:
        raise ValueError("cannot normalize a zero embedding")
    normalized = tuple(value / magnitude for value in validated)
    return validate_embedding(normalized, dimension=len(validated))


def validate_normalized_embedding(
    vector: tuple[float, ...], *, dimension: int | None = None
) -> Embedding:
    validated = validate_embedding(vector, dimension=dimension)
    magnitude = math.sqrt(math.fsum(value * value for value in validated))
    if not math.isclose(magnitude, 1.0, rel_tol=1e-6, abs_tol=1e-6):
        raise ValueError("embedding must be normalized to unit length")
    return validated


def cosine_similarity(left: tuple[float, ...], right: tuple[float, ...]) -> float:
    left_normalized = normalize_embedding(left)
    right_normalized = normalize_embedding(right)
    if len(left_normalized) != len(right_normalized):
        raise ValueError(
            f"embedding dimensions differ: {len(left_normalized)} != {len(right_normalized)}"
        )
    return max(
        -1.0,
        min(
            1.0,
            math.fsum(
                a * b
                for a, b in zip(left_normalized, right_normalized, strict=True)
            ),
        ),
    )


@dataclass(frozen=True, slots=True)
class EmbeddingRequest:
    modality: Modality
    text: str | None = None
    image_bytes: bytes | None = None

    def __post_init__(self) -> None:
        try:
            object.__setattr__(self, "modality", Modality(self.modality))
        except ValueError as error:
            raise ValueError("embedding request modality is unsupported") from error
        if self.modality is Modality.TEXT:
            if self.text is None:
                raise ValueError("text is required for a text embedding request")
            _require_text("text", self.text)
            if self.image_bytes is not None:
                raise ValueError("image_bytes is not allowed for a text embedding request")
        elif self.modality is Modality.IMAGE:
            if not isinstance(self.image_bytes, bytes) or not self.image_bytes:
                raise ValueError("non-empty image_bytes are required for an image request")
            if self.text is not None:
                raise ValueError("text is not allowed for an image embedding request")


@dataclass(frozen=True, slots=True)
class EmbeddingResult:
    vector: Embedding
    model: str
    model_version: str
    dimension: int
    synthetic: bool = False

    def __post_init__(self) -> None:
        _require_text("model", self.model)
        _require_text("model_version", self.model_version)
        if not 1 <= self.dimension <= 4096:
            raise ValueError("dimension must be between 1 and 4096")
        object.__setattr__(
            self,
            "vector",
            validate_normalized_embedding(self.vector, dimension=self.dimension),
        )


@dataclass(frozen=True, slots=True)
class IndexedMultimodalRecord:
    id: str
    tenant_id: str
    source_type: str
    source_id: str
    modality: Modality
    embedding: Embedding
    embedding_model: str
    embedding_model_version: str
    embedding_dimension: int
    content: str | None = None
    source_uri: str | None = None
    metadata: Metadata = field(default_factory=dict)
    status: RetrievalStatus = RetrievalStatus.READY
    campaign_id: str | None = None
    asset_id: str | None = None
    object_key: str | None = None
    asset_kind: AssetKind | str | None = None
    media_type: str | None = None
    brand: str | None = None
    campaign_category: str | None = None
    approval_status: ApprovalStatus = ApprovalStatus.APPROVED
    policy_status: PolicyStatus = PolicyStatus.ALLOWED
    source_hash: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    indexed_at: datetime | None = None

    def __post_init__(self) -> None:
        try:
            object.__setattr__(self, "modality", Modality(self.modality))
            object.__setattr__(self, "status", RetrievalStatus(self.status))
            object.__setattr__(
                self, "approval_status", ApprovalStatus(self.approval_status)
            )
            object.__setattr__(self, "policy_status", PolicyStatus(self.policy_status))
        except ValueError as error:
            raise ValueError("retrieval record contains an unsupported enum value") from error
        for name in ("id", "tenant_id", "source_id"):
            _require_safe_id(name, getattr(self, name))
        for name in ("source_type", "embedding_model", "embedding_model_version"):
            _require_text(name, getattr(self, name))
        if not 1 <= self.embedding_dimension <= 4096:
            raise ValueError("embedding_dimension must be between 1 and 4096")
        object.__setattr__(
            self,
            "embedding",
            validate_normalized_embedding(
                self.embedding, dimension=self.embedding_dimension
            ),
        )
        if self.content is not None:
            _require_text("content", self.content)
            if len(self.content) > 100_000:
                raise ValueError("content exceeds 100000 characters")
        if self.source_uri is not None:
            _require_text("source_uri", self.source_uri)
            if len(self.source_uri) > 2_000:
                raise ValueError("source_uri exceeds 2000 characters")
        for name in ("campaign_id", "asset_id"):
            value = getattr(self, name)
            if value is not None:
                _require_safe_id(name, value)
        if self.object_key is not None:
            _require_object_key(self.object_key)
        if self.media_type is not None:
            _require_text("media_type", self.media_type)
        for name in ("brand", "campaign_category"):
            value = getattr(self, name)
            if value is not None:
                _require_text(name, value)
                if len(value) > 160:
                    raise ValueError(f"{name} exceeds 160 characters")
        if self.source_hash is not None and not _SHA256.fullmatch(self.source_hash):
            raise ValueError("source_hash must be a lowercase SHA-256 digest")
        if self.asset_kind is not None:
            try:
                object.__setattr__(self, "asset_kind", AssetKind(self.asset_kind))
            except ValueError as error:
                raise ValueError("asset_kind is unsupported") from error
        object.__setattr__(self, "metadata", _validate_metadata(self.metadata, name="metadata"))
        for name in ("created_at", "updated_at", "indexed_at"):
            value = getattr(self, name)
            if value is not None and (value.tzinfo is None or value.utcoffset() is None):
                raise ValueError(f"{name} must be timezone-aware")

    @classmethod
    def create(
        cls,
        *,
        tenant_id: str,
        source_type: str,
        source_id: str,
        modality: Modality,
        embedding_result: EmbeddingResult,
        source_hash: str,
        **values: object,
    ) -> IndexedMultimodalRecord:
        now = datetime.now(UTC)
        return cls(
            id=f"ret_{uuid4().hex[:16]}",
            tenant_id=tenant_id,
            source_type=source_type,
            source_id=source_id,
            modality=modality,
            embedding=embedding_result.vector,
            embedding_model=embedding_result.model,
            embedding_model_version=embedding_result.model_version,
            embedding_dimension=embedding_result.dimension,
            source_hash=source_hash,
            created_at=now,
            updated_at=now,
            indexed_at=now,
            **values,  # type: ignore[arg-type]
        )

    @property
    def model_identity(self) -> str:
        return f"{self.embedding_model}:{self.embedding_model_version}:{self.embedding_dimension}"


@dataclass(frozen=True, slots=True)
class SearchRequest:
    tenant_id: str
    query_embedding: Embedding
    embedding_model: str
    embedding_model_version: str
    embedding_dimension: int
    top_k: int = 10
    candidate_limit: int = 1000
    filters: Metadata = field(default_factory=dict)
    min_similarity: float = -1.0
    approved_only: bool = True
    allowed_kinds: tuple[AssetKind, ...] = ()
    campaign_id: str | None = None
    exclude_campaign_id: str | None = None

    def __post_init__(self) -> None:
        for name in ("tenant_id", "embedding_model", "embedding_model_version"):
            _require_text(name, getattr(self, name))
        if not 1 <= self.embedding_dimension <= 4096:
            raise ValueError("embedding_dimension must be between 1 and 4096")
        object.__setattr__(
            self,
            "query_embedding",
            normalize_embedding(
                validate_embedding(
                    self.query_embedding,
                    dimension=self.embedding_dimension,
                )
            ),
        )
        if not 1 <= self.top_k <= 100:
            raise ValueError("top_k must be between 1 and 100")
        if not self.top_k <= self.candidate_limit <= 10_000:
            raise ValueError("candidate_limit must be between top_k and 10000")
        if not math.isfinite(self.min_similarity) or not -1.0 <= self.min_similarity <= 1.0:
            raise ValueError("min_similarity must be finite and between -1 and 1")
        object.__setattr__(self, "filters", _validate_metadata(self.filters, name="filters"))
        for name in ("campaign_id", "exclude_campaign_id"):
            value = getattr(self, name)
            if value is not None:
                _require_safe_id(name, value)
        object.__setattr__(
            self,
            "allowed_kinds",
            tuple(AssetKind(value) for value in self.allowed_kinds),
        )


@dataclass(frozen=True, slots=True)
class SearchResult:
    record: IndexedMultimodalRecord
    similarity: float
    rerank_score: float | None = None
    rank: int | None = None
    reasons: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not math.isfinite(self.similarity) or not -1.0 <= self.similarity <= 1.0:
            raise ValueError("similarity must be finite and between -1 and 1")
        if self.rerank_score is not None and (
            not math.isfinite(self.rerank_score) or not 0.0 <= self.rerank_score <= 1.0
        ):
            raise ValueError("rerank_score must be finite and between 0 and 1")
        if self.rank is not None and self.rank < 1:
            raise ValueError("rank must be positive")


@dataclass(frozen=True, slots=True)
class RelevanceJudgment:
    tenant_id: str
    query_id: str
    record_id: str
    relevance: int

    def __post_init__(self) -> None:
        for name in ("tenant_id", "query_id", "record_id"):
            _require_text(name, getattr(self, name))
        if (
            isinstance(self.relevance, bool)
            or not isinstance(self.relevance, int)
            or not 0 <= self.relevance <= 3
        ):
            raise ValueError("relevance must be an integer between 0 and 3")


@dataclass(frozen=True, slots=True)
class IndexingSummary:
    campaign_id: str
    indexed: int
    skipped: int
    failed: int
    record_ids: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _require_safe_id("campaign_id", self.campaign_id)
        if min(self.indexed, self.skipped, self.failed) < 0:
            raise ValueError("indexing counts cannot be negative")


@dataclass(frozen=True, slots=True)
class RetrievalStatusSummary:
    campaign_id: str
    total: int
    ready: int
    failed: int
    quarantined: int
    model: str
    model_version: str
    synthetic: bool


def json_record(
    record: IndexedMultimodalRecord, *, include_embedding: bool = False
) -> dict[str, object]:
    """Return a stable API-safe representation without exposing vectors by default."""
    result: dict[str, object] = {
        "id": record.id,
        "source_type": record.source_type,
        "source_id": record.source_id,
        "modality": record.modality.value,
        "model": record.embedding_model,
        "model_version": record.embedding_model_version,
        "dimension": record.embedding_dimension,
        "content": record.content,
        "object_key": record.object_key,
        "asset_kind": record.asset_kind.value if isinstance(record.asset_kind, AssetKind) else None,
        "media_type": record.media_type,
        "brand": record.brand,
        "campaign_category": record.campaign_category,
        "approval_status": record.approval_status.value,
        "policy_status": record.policy_status.value,
        "source_hash": record.source_hash,
        "campaign_id": record.campaign_id,
    }
    if include_embedding:
        result["embedding"] = list(record.embedding)
    return result
