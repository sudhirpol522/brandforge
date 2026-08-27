from __future__ import annotations

import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from brandforge.editor import (
    MAX_DOCUMENT_BYTES,
    MAX_FABRIC_BYTES,
    MAX_LAYERS,
    MAX_PREVIEW_BYTES,
    MAX_SVG_BYTES,
)

DesignChannelValue = Literal["instagram", "email", "web", "presentation"]


def _default_channels() -> list[DesignChannelValue]:
    return ["instagram", "email", "web", "presentation"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class CampaignBriefRequest(StrictModel):
    product_name: str = Field(min_length=2, max_length=120)
    objective: str = Field(min_length=5, max_length=1200)
    audience: str = Field(min_length=2, max_length=500)
    channels: list[Literal["instagram", "email", "web", "presentation"]] = Field(
        default_factory=_default_channels,
        min_length=1,
        max_length=4,
    )
    call_to_action: str = Field(default="Learn more", max_length=80)
    locale: str = Field(default="en-US", pattern=r"^[a-z]{2}(?:-[A-Z]{2})?$")
    constraints: list[str] = Field(default_factory=list, max_length=20)


class LayerDocumentRequest(StrictModel):
    schema_version: Literal[1] = 1
    channel: DesignChannelValue | None = None
    width: int = Field(gt=0, le=4096)
    height: int = Field(gt=0, le=4096)
    layers: list[dict[str, Any]] = Field(max_length=MAX_LAYERS)

    @field_validator("layers")
    @classmethod
    def bounded_document(cls, value: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if len(json.dumps(value, separators=(",", ":")).encode()) > MAX_DOCUMENT_BYTES:
            raise ValueError("layer document exceeds the 2 MiB limit")
        return value


class LayerDocumentResponse(StrictModel):
    schema_version: Literal[1]
    channel: DesignChannelValue
    width: int
    height: int
    layers: list[dict[str, Any]]


class DesignRevisionResponse(StrictModel):
    id: str
    channel: DesignChannelValue
    revision: int = Field(ge=1)
    layer_document_key: str
    fabric_json_key: str
    svg_key: str
    preview_png_key: str | None
    editor: str
    editor_version: str
    created_by: str
    created_at: str
    hashes: dict[str, str]


class SaveDesignRequest(StrictModel):
    channel: DesignChannelValue | None = None
    layer_document: LayerDocumentRequest
    fabric_json: dict[str, Any]
    svg: str = Field(min_length=1, max_length=MAX_SVG_BYTES)
    preview_png_base64: str | None = Field(
        default=None,
        max_length=((MAX_PREVIEW_BYTES + 2) // 3) * 4,
    )
    expected_revision: int = Field(ge=0)
    editor_version: str = Field(default="7", min_length=1, max_length=100)

    @field_validator("fabric_json")
    @classmethod
    def bounded_fabric_json(cls, value: dict[str, Any]) -> dict[str, Any]:
        if len(json.dumps(value, separators=(",", ":")).encode()) > MAX_FABRIC_BYTES:
            raise ValueError("Fabric cache exceeds the 5 MiB limit")
        return value


class DesignResponse(StrictModel):
    campaign_id: str
    campaign_version: int = Field(ge=1)
    revision: int = Field(ge=0)
    revision_metadata: DesignRevisionResponse | None
    layer_document: LayerDocumentResponse
    fabric_json: dict[str, Any]
    svg: str
    campaign: dict[str, Any]


class CreateCampaignRequest(StrictModel):
    name: str = Field(min_length=2, max_length=160)
    brief: CampaignBriefRequest
    brand_guide_text: str | None = Field(default=None, max_length=250_000)


class BrandGuideRequest(StrictModel):
    text: str = Field(min_length=20, max_length=250_000)


class ApprovalRequest(StrictModel):
    decision: Literal["approved", "rejected", "changes_requested"]
    comments: str = Field(default="", max_length=1000)
    reason_codes: list[str] = Field(default_factory=list, max_length=10)
    corrections: dict[str, Any] | None = None


class SelectionRequest(StrictModel):
    variant_id: str = Field(pattern=r"^var_[a-f0-9]{12}$")
    reason_code: Literal[
        "brief_match",
        "brand_match",
        "visual_quality",
        "accessibility",
        "audience_fit",
        "other",
    ]
    explanation: str = Field(min_length=2, max_length=1000)


class RetrievalTextRequest(StrictModel):
    query: str = Field(min_length=1, max_length=2000)
    limit: int = Field(default=10, ge=1, le=20)


class RetrievalSearchResponse(StrictModel):
    campaign_id: str
    query_modality: Literal["text", "image"]
    model: str
    model_version: str
    synthetic: bool
    results: list[dict[str, Any]]


class RetrievalStatusResponse(StrictModel):
    campaign_id: str
    total: int = Field(ge=0)
    ready: int = Field(ge=0)
    failed: int = Field(ge=0)
    quarantined: int = Field(ge=0)
    model: str
    model_version: str
    synthetic: bool


class RetrievalBackfillResponse(StrictModel):
    summaries: list[dict[str, Any]]


class CuratePreferenceRequest(StrictModel):
    status: Literal["curated", "rejected"]
    dataset_version: str = Field(min_length=1, max_length=100)


class PreferenceDatasetImportRequest(StrictModel):
    dataset_version: str = Field(min_length=1, max_length=100)
    rows: list[dict[str, Any]] = Field(min_length=1, max_length=10_000)


class PreferenceDatasetResponse(StrictModel):
    dataset_version: str
    tenant_id: str
    row_count: int = Field(ge=0)
    fingerprint: str
    rows: list[dict[str, Any]]
    synthetic: bool


class CampaignResponse(StrictModel):
    campaign: dict[str, Any]


class CampaignListResponse(StrictModel):
    campaigns: list[dict[str, Any]]


class EventListResponse(StrictModel):
    events: list[dict[str, Any]]


class ErrorResponse(StrictModel):
    error: str
    message: str
    trace_id: str | None = None


class AssetUploadResponse(StrictModel):
    asset: dict[str, Any]
    campaign: dict[str, Any]


class CancelRequest(StrictModel):
    reason: str = Field(default="user_requested", max_length=200)


class HealthResponse(StrictModel):
    status: Literal["ok", "degraded"]
    version: str


class TenantContext(BaseModel):
    tenant_id: str
    user_id: str
    role: str

    @field_validator("tenant_id", "user_id", "role")
    @classmethod
    def safe_identifier(cls, value: str) -> str:
        allowed = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_.:@")
        if not value or len(value) > 100 or any(char not in allowed for char in value):
            raise ValueError("identity header contains unsupported characters")
        return value
