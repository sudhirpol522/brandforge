from __future__ import annotations

from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, cast
from uuid import uuid4


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


class CampaignStatus(StrEnum):
    CREATED = "created"
    ASSETS_PROCESSING = "assets_processing"
    BRAND_RULES_PENDING_APPROVAL = "brand_rules_pending_approval"
    PLAN_PENDING_APPROVAL = "plan_pending_approval"
    GENERATING = "generating"
    EVALUATING = "evaluating"
    VARIANTS_PENDING_APPROVAL = "variants_pending_approval"
    REVISING = "revising"
    FINAL_APPROVAL = "final_approval"
    EXPORTING = "exporting"
    COMPLETED = "completed"
    FAILED_RETRYABLE = "failed_retryable"
    FAILED_PERMANENT = "failed_permanent"
    CANCELLED = "cancelled"


class ApprovalGate(StrEnum):
    BRAND_RULES = "brand_rules"
    PLAN = "plan"
    VARIANT = "variant"
    FINAL = "final"


class ApprovalDecision(StrEnum):
    APPROVED = "approved"
    REJECTED = "rejected"
    CHANGES_REQUESTED = "changes_requested"


class DesignChannel(StrEnum):
    INSTAGRAM = "instagram"
    EMAIL = "email"
    WEB = "web"
    PRESENTATION = "presentation"


@dataclass(slots=True)
class LayerDocument:
    """Vendor-neutral, authoritative representation of an editable design."""

    channel: DesignChannel
    width: int
    height: int
    layers: list[dict[str, Any]]
    schema_version: int = 1


@dataclass(frozen=True, slots=True)
class DesignRevision:
    """Immutable metadata for one channel design revision."""

    id: str
    channel: DesignChannel
    revision: int
    layer_document_key: str
    fabric_json_key: str
    svg_key: str
    preview_png_key: str | None
    editor: str
    editor_version: str
    created_by: str
    created_at: str
    hashes: dict[str, str]


@dataclass(slots=True)
class CampaignBrief:
    product_name: str
    objective: str
    audience: str
    channels: list[str] = field(
        default_factory=lambda: ["instagram", "email", "web", "presentation"]
    )
    call_to_action: str = "Learn more"
    locale: str = "en-US"
    constraints: list[str] = field(default_factory=list)


@dataclass(slots=True)
class BrandRules:
    colors: list[str]
    fonts: list[str]
    tone: list[str]
    prohibited_terms: list[str]
    required_disclaimers: list[str]
    logo_clear_space_px: int
    allowed_logo_backgrounds: list[str]
    evidence: dict[str, list[str]] = field(default_factory=dict)
    confidence: float = 0.0
    warnings: list[str] = field(default_factory=list)
    version: int = 1


@dataclass(slots=True)
class CampaignPlan:
    objective: str
    audience: str
    key_messages: list[str]
    visual_direction: str
    channel_deliverables: dict[str, str]
    required_assets: list[str]
    claims_requiring_review: list[str]
    success_criteria: list[str]
    revision: int = 1


@dataclass(slots=True)
class ScoreBreakdown:
    brief_alignment: float = 0.0
    visual_alignment: float = 0.0
    copy_image_consistency: float = 0.0
    visual_quality: float = 0.0
    brand_compliance: float = 0.0
    accessibility: float = 0.0
    claims_safety: float = 0.0
    preference: float = 0.5
    diversity: float = 1.0
    final: float = 0.0
    scorer_mode: str = "deterministic_multimodal_fallback"


@dataclass(slots=True)
class CampaignVariant:
    id: str
    concept: str
    rationale: str
    copy_by_channel: dict[str, dict[str, str]]
    visual_prompt: str
    alt_text: str
    image_tags: list[str]
    palette: list[str]
    scores: ScoreBreakdown = field(default_factory=ScoreBreakdown)
    violations: list[str] = field(default_factory=list)
    estimated_cost_usd: float = 0.0
    rank: int | None = None
    provider_asset_url: str | None = None
    provider_asset_id: str | None = None
    asset_object_key: str | None = None
    image_embedding: list[float] | None = None


@dataclass(slots=True)
class ApprovalRecord:
    id: str
    gate: ApprovalGate
    decision: ApprovalDecision
    reviewer_id: str
    reviewer_role: str
    artifact_version: int
    comments: str
    reason_codes: list[str]
    created_at: str = field(default_factory=utc_now)


@dataclass(slots=True)
class PreferenceFeedback:
    id: str
    reviewer_id: str
    preferred_variant_id: str
    rejected_variant_ids: list[str]
    reason_code: str
    explanation: str
    created_at: str = field(default_factory=utc_now)
    curated: bool = False
    preferred_features: dict[str, float] = field(default_factory=dict)
    rejected_features: dict[str, dict[str, float]] = field(default_factory=dict)
    display_ranks: dict[str, int] = field(default_factory=dict)
    presentation_order: list[str] = field(default_factory=list)
    brand: str = ""
    campaign_category: str = "general"
    brief_fingerprint: str = ""
    curation_status: str = "raw"
    curated_by: str | None = None
    curated_at: str | None = None
    dataset_version: str | None = None
    source_version: str = "selection-snapshot-v1"


@dataclass(slots=True)
class AssetRecord:
    id: str
    object_key: str
    filename: str
    media_type: str
    sha256: str
    size_bytes: int
    kind: str
    status: str = "normalized"
    created_at: str = field(default_factory=utc_now)


@dataclass(slots=True)
class ExportManifest:
    id: str
    campaign_id: str
    object_key: str
    variant_id: str
    formats: dict[str, str]
    provenance: dict[str, Any]
    created_at: str = field(default_factory=utc_now)


@dataclass(slots=True)
class Campaign:
    id: str
    tenant_id: str
    name: str
    brief: CampaignBrief
    status: CampaignStatus = CampaignStatus.CREATED
    brand_rules: BrandRules | None = None
    plan: CampaignPlan | None = None
    variants: list[CampaignVariant] = field(default_factory=list)
    selected_variant_id: str | None = None
    approvals: list[ApprovalRecord] = field(default_factory=list)
    feedback: list[PreferenceFeedback] = field(default_factory=list)
    assets: list[AssetRecord] = field(default_factory=list)
    agent_traces: list[dict[str, Any]] = field(default_factory=list)
    export: ExportManifest | None = None
    designs: dict[str, list[DesignRevision]] = field(default_factory=dict)
    trace_id: str = field(default_factory=lambda: uuid4().hex)
    workflow_version: str = "workflow-v1"
    agent_graph_version: str = "agent-graph-v1"
    prompt_versions: dict[str, str] = field(
        default_factory=lambda: {
            "brand_compiler": "1.0",
            "planner": "1.0",
            "creative": "1.0",
            "critics": "1.0",
        }
    )
    model_manifest: dict[str, str] = field(default_factory=dict)
    total_cost_usd: float = 0.0
    version: int = 0
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)

    @classmethod
    def create(cls, tenant_id: str, name: str, brief: CampaignBrief) -> Campaign:
        return cls(id=f"cmp_{uuid4().hex[:16]}", tenant_id=tenant_id, name=name, brief=brief)

    def selected_variant(self) -> CampaignVariant | None:
        return next((item for item in self.variants if item.id == self.selected_variant_id), None)

    def to_dict(self) -> dict[str, Any]:
        return cast(dict[str, Any], _jsonable(self))

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> Campaign:
        brief = CampaignBrief(**raw["brief"])
        rules = BrandRules(**raw["brand_rules"]) if raw.get("brand_rules") else None
        plan = CampaignPlan(**raw["plan"]) if raw.get("plan") else None
        variants = []
        for item in raw.get("variants", []):
            variant = dict(item)
            variant["scores"] = ScoreBreakdown(**variant.get("scores", {}))
            variants.append(CampaignVariant(**variant))
        approvals = [
            ApprovalRecord(
                **{
                    **item,
                    "gate": ApprovalGate(item["gate"]),
                    "decision": ApprovalDecision(item["decision"]),
                }
            )
            for item in raw.get("approvals", [])
        ]
        feedback = [PreferenceFeedback(**item) for item in raw.get("feedback", [])]
        assets = [AssetRecord(**item) for item in raw.get("assets", [])]
        export = ExportManifest(**raw["export"]) if raw.get("export") else None
        designs = {
            channel: [
                DesignRevision(
                    **{
                        **item,
                        "channel": DesignChannel(item.get("channel", channel)),
                    }
                )
                for item in revisions
            ]
            for channel, revisions in raw.get("designs", {}).items()
        }
        scalar = {
            key: value
            for key, value in raw.items()
            if key
            not in {
                "brief",
                "brand_rules",
                "plan",
                "variants",
                "approvals",
                "feedback",
                "assets",
                "export",
                "designs",
                "status",
            }
        }
        return cls(
            **scalar,
            brief=brief,
            status=CampaignStatus(raw["status"]),
            brand_rules=rules,
            plan=plan,
            variants=variants,
            approvals=approvals,
            feedback=feedback,
            assets=assets,
            export=export,
            designs=designs,
        )


@dataclass(slots=True)
class OutboxEvent:
    id: str
    tenant_id: str
    aggregate_id: str
    event_type: str
    payload: dict[str, Any]
    occurred_at: str = field(default_factory=utc_now)
    published_at: str | None = None

    @classmethod
    def create(
        cls, tenant_id: str, aggregate_id: str, event_type: str, payload: dict[str, Any]
    ) -> OutboxEvent:
        return cls(
            id=f"evt_{uuid4().hex[:16]}",
            tenant_id=tenant_id,
            aggregate_id=aggregate_id,
            event_type=event_type,
            payload=payload,
        )


def _jsonable(value: Any) -> Any:
    if isinstance(value, StrEnum):
        return value.value
    if is_dataclass(value):
        return {
            key: _jsonable(item)
            for key, item in asdict(value).items()  # type: ignore[arg-type]
        }
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value
