from __future__ import annotations

import hashlib
import io
from collections.abc import Callable, Iterable
from dataclasses import asdict
from typing import Any

from .domain import Campaign, CampaignStatus
from .exceptions import ValidationError
from .ports import CampaignRepository, EmbeddingProvider, ObjectStore, RetrievalRepository
from .retrieval import (
    ApprovalStatus,
    AssetKind,
    IndexedMultimodalRecord,
    IndexingSummary,
    Modality,
    PolicyStatus,
    RetrievalStatus,
    RetrievalStatusSummary,
    SearchRequest,
    SearchResult,
)

MAX_QUERY_CHARACTERS = 2_000
MAX_PDF_PAGES = 100
MAX_CHUNKS_PER_ASSET = 250
CHUNK_CHARACTERS = 1_600
CHUNK_OVERLAP = 200
SUPPORTED_IMAGE_TYPES = {"image/png", "image/jpeg"}


class MultimodalRetrievalService:
    """Indexes approved campaign material and performs policy-safe two-stage search."""

    def __init__(
        self,
        *,
        campaigns: CampaignRepository,
        repository: RetrievalRepository,
        embeddings: EmbeddingProvider,
        object_store: ObjectStore,
        candidate_limit: int = 50,
    ) -> None:
        if not 1 <= candidate_limit <= 50:
            raise ValueError("candidate_limit must be between 1 and 50")
        self.campaigns = campaigns
        self.repository = repository
        self.embeddings = embeddings
        self.object_store = object_store
        self.candidate_limit = candidate_limit

    @property
    def synthetic(self) -> bool:
        return self.embeddings.model_name.startswith("deterministic-")

    def index_campaign(self, tenant_id: str, campaign_id: str) -> IndexingSummary:
        campaign = self.campaigns.get(tenant_id, campaign_id)
        indexed: list[str] = []
        skipped = 0
        failed = 0
        warnings: list[str] = []

        for asset in campaign.assets:
            if asset.status in {"quarantined", "blocked", "failed", "rejected"}:
                skipped += 1
                continue
            approved = asset.status == "approved" or asset.kind == "approved_example"
            approved = approved or campaign.status is CampaignStatus.COMPLETED
            if not approved:
                skipped += 1
                continue
            try:
                content = self.object_store.get(asset.object_key)
                records = self._asset_records(campaign, asset, content)
                if not records:
                    skipped += 1
                for record in records:
                    indexed.append(self.repository.upsert(record).id)
            except Exception as error:
                failed += 1
                warnings.append(f"{asset.id}: {type(error).__name__}")

        if campaign.status is CampaignStatus.COMPLETED:
            record_factories: tuple[
                Callable[[Campaign], IndexedMultimodalRecord | None], ...
            ] = (self._campaign_copy_record, self._campaign_visual_record)
            for record_factory in record_factories:
                try:
                    campaign_record = record_factory(campaign)
                    if campaign_record is None:
                        skipped += 1
                    else:
                        indexed.append(self.repository.upsert(campaign_record).id)
                except Exception as error:
                    failed += 1
                    warnings.append(f"{record_factory.__name__}: {type(error).__name__}")

        return IndexingSummary(
            campaign_id=campaign.id,
            indexed=len(indexed),
            skipped=skipped,
            failed=failed,
            record_ids=tuple(indexed),
            warnings=tuple(warnings),
        )

    def backfill(self, tenant_id: str, campaign_id: str | None = None) -> list[IndexingSummary]:
        if campaign_id is not None:
            return [self.index_campaign(tenant_id, campaign_id)]
        return [
            self.index_campaign(tenant_id, campaign.id)
            for campaign in self.campaigns.list(tenant_id)
        ]

    def status(self, tenant_id: str, campaign_id: str) -> RetrievalStatusSummary:
        self.campaigns.get(tenant_id, campaign_id)
        records = self.repository.list(
            tenant_id,
            campaign_id=campaign_id,
            embedding_model=self.embeddings.model_name,
            embedding_model_version=self.embeddings.model_version,
            limit=10_000,
        )
        return RetrievalStatusSummary(
            campaign_id=campaign_id,
            total=len(records),
            ready=sum(record.status is RetrievalStatus.READY for record in records),
            failed=sum(record.status is RetrievalStatus.FAILED for record in records),
            quarantined=sum(
                record.status is RetrievalStatus.QUARANTINED for record in records
            ),
            model=self.embeddings.model_name,
            model_version=self.embeddings.model_version,
            synthetic=self.synthetic,
        )

    def search_text(
        self,
        tenant_id: str,
        campaign_id: str,
        query: str,
        *,
        limit: int = 10,
    ) -> list[SearchResult]:
        if not isinstance(query, str) or not query.strip():
            raise ValidationError("retrieval query must be non-empty")
        if len(query) > MAX_QUERY_CHARACTERS:
            raise ValidationError(
                f"retrieval query exceeds {MAX_QUERY_CHARACTERS} characters"
            )
        campaign = self.campaigns.get(tenant_id, campaign_id)
        embedding = self.embeddings.embed_text(query.strip())
        return self._search(campaign, embedding.vector, limit)

    def search_image(
        self,
        tenant_id: str,
        campaign_id: str,
        image_bytes: bytes,
        *,
        limit: int = 10,
    ) -> list[SearchResult]:
        campaign = self.campaigns.get(tenant_id, campaign_id)
        embedding = self.embeddings.embed_image(image_bytes)
        return self._search(campaign, embedding.vector, limit)

    def trace_context(
        self,
        tenant_id: str,
        campaign_id: str,
        query: str,
        *,
        limit: int = 5,
    ) -> tuple[list[dict[str, object]], dict[str, object]]:
        results = self.search_text(tenant_id, campaign_id, query, limit=limit)
        references: list[dict[str, object]] = [
            {
                "retrieval_id": result.record.id,
                "source_id": result.record.source_id,
                "source_type": result.record.source_type,
                "object_key": result.record.object_key,
                "content": result.record.content,
                "score": result.rerank_score,
                "model": result.record.embedding_model,
                "model_version": result.record.embedding_model_version,
            }
            for result in results
        ]
        trace = {
            "agent": "multimodal_retrieval",
            "version": "1.0",
            "decision_summary": f"Selected {len(references)} approved references.",
            "tool_calls": [
                {
                    "tool": "vector_search_and_policy_rerank",
                    "candidate_limit": self.candidate_limit,
                    "result_ids": [result.record.id for result in results],
                    "scores": [result.rerank_score for result in results],
                    "model": self.embeddings.model_name,
                    "model_version": self.embeddings.model_version,
                }
            ],
            "warnings": ["synthetic embedding provider"] if self.synthetic else [],
            "cost_usd": 0.0,
        }
        return references, trace

    def _search(
        self,
        campaign: Campaign,
        query_embedding: tuple[float, ...],
        limit: int,
    ) -> list[SearchResult]:
        limit = max(1, min(limit, 20))
        candidates = self.repository.search(
            SearchRequest(
                tenant_id=campaign.tenant_id,
                query_embedding=query_embedding,
                embedding_model=self.embeddings.model_name,
                embedding_model_version=self.embeddings.model_version,
                embedding_dimension=self.embeddings.dimension,
                top_k=self.candidate_limit,
                candidate_limit=max(self.candidate_limit, limit),
                approved_only=True,
            )
        )
        return _rerank(campaign, candidates, limit=limit)

    def _asset_records(
        self,
        campaign: Campaign,
        asset: Any,
        content: bytes,
    ) -> list[IndexedMultimodalRecord]:
        if asset.media_type in SUPPORTED_IMAGE_TYPES:
            embedding = self.embeddings.embed_image(content)
            kind = (
                AssetKind.APPROVED_EXAMPLE
                if asset.kind == "approved_example"
                else AssetKind.PRODUCT_ASSET
            )
            return [
                IndexedMultimodalRecord.create(
                    tenant_id=campaign.tenant_id,
                    source_type="asset",
                    source_id=asset.id,
                    modality=Modality.IMAGE,
                    embedding_result=embedding,
                    source_hash=asset.sha256,
                    campaign_id=campaign.id,
                    asset_id=asset.id,
                    object_key=asset.object_key,
                    source_uri=asset.object_key,
                    asset_kind=kind,
                    media_type=asset.media_type,
                    brand=campaign.brief.product_name,
                    campaign_category=_campaign_category(campaign),
                    approval_status=ApprovalStatus.APPROVED,
                    policy_status=PolicyStatus.ALLOWED,
                    metadata={"filename": asset.filename, "asset_status": asset.status},
                )
            ]
        if asset.media_type not in {"application/pdf", "text/plain"}:
            return []
        text = _extract_text(content, asset.media_type)
        records: list[IndexedMultimodalRecord] = []
        for index, chunk in enumerate(_chunks(text)):
            source_id = f"{asset.id}-chunk-{index + 1}"
            source_hash = hashlib.sha256(
                f"{asset.sha256}:{index}:{chunk}".encode()
            ).hexdigest()
            records.append(
                IndexedMultimodalRecord.create(
                    tenant_id=campaign.tenant_id,
                    source_type=(
                        "pdf_chunk"
                        if asset.media_type == "application/pdf"
                        else "text_chunk"
                    ),
                    source_id=source_id,
                    modality=Modality.TEXT,
                    embedding_result=self.embeddings.embed_text(chunk),
                    source_hash=source_hash,
                    content=chunk,
                    campaign_id=campaign.id,
                    asset_id=asset.id,
                    object_key=asset.object_key,
                    source_uri=asset.object_key,
                    asset_kind=AssetKind.PDF_CHUNK,
                    media_type=asset.media_type,
                    brand=campaign.brief.product_name,
                    campaign_category=_campaign_category(campaign),
                    approval_status=ApprovalStatus.APPROVED,
                    policy_status=PolicyStatus.ALLOWED,
                    metadata={"chunk": index + 1, "filename": asset.filename},
                )
            )
        return records

    def _campaign_copy_record(self, campaign: Campaign) -> IndexedMultimodalRecord | None:
        variant = campaign.selected_variant()
        if variant is None:
            return None
        parts = [variant.concept, variant.rationale]
        for channel, copy in sorted(variant.copy_by_channel.items()):
            parts.append(channel)
            parts.extend(str(value) for _, value in sorted(copy.items()))
        content = "\n".join(part for part in parts if part.strip())
        source_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
        return IndexedMultimodalRecord.create(
            tenant_id=campaign.tenant_id,
            source_type="completed_campaign_copy",
            source_id=f"{campaign.id}-copy",
            modality=Modality.TEXT,
            embedding_result=self.embeddings.embed_text(content),
            source_hash=source_hash,
            content=content,
            campaign_id=campaign.id,
            asset_kind=AssetKind.CAMPAIGN_COPY,
            media_type="text/plain",
            brand=campaign.brief.product_name,
            campaign_category=_campaign_category(campaign),
            approval_status=ApprovalStatus.APPROVED,
            policy_status=PolicyStatus.ALLOWED,
            metadata={"variant_id": variant.id},
        )

    def _campaign_visual_record(self, campaign: Campaign) -> IndexedMultimodalRecord | None:
        variant = campaign.selected_variant()
        if variant is None or variant.asset_object_key is None:
            return None
        content = self.object_store.get(variant.asset_object_key)
        source_hash = hashlib.sha256(content).hexdigest()
        media_type = _media_type_for_object_key(variant.asset_object_key)
        if media_type == "image/svg+xml" and not self.synthetic:
            return None
        return IndexedMultimodalRecord.create(
            tenant_id=campaign.tenant_id,
            source_type="completed_campaign_visual",
            source_id=f"{campaign.id}-visual",
            modality=Modality.IMAGE,
            embedding_result=self.embeddings.embed_image(content),
            source_hash=source_hash,
            campaign_id=campaign.id,
            object_key=variant.asset_object_key,
            source_uri=variant.asset_object_key,
            asset_kind=AssetKind.CAMPAIGN_VISUAL,
            media_type=media_type,
            brand=campaign.brief.product_name,
            campaign_category=_campaign_category(campaign),
            approval_status=ApprovalStatus.APPROVED,
            policy_status=PolicyStatus.ALLOWED,
            metadata={"variant_id": variant.id},
        )


def _rerank(
    campaign: Campaign,
    candidates: Iterable[SearchResult],
    *,
    limit: int,
) -> list[SearchResult]:
    scored: list[tuple[float, SearchResult, tuple[str, ...]]] = []
    category = _campaign_category(campaign)
    for candidate in candidates:
        record = candidate.record
        if (
            record.approval_status is not ApprovalStatus.APPROVED
            or record.policy_status is not PolicyStatus.ALLOWED
        ):
            continue
        exact = (candidate.similarity + 1.0) / 2.0
        brand_bonus = 0.08 if record.brand == campaign.brief.product_name else 0.0
        category_bonus = 0.08 if record.campaign_category == category else 0.0
        provenance_bonus = 0.04 if record.source_hash and record.object_key else 0.02
        score = min(1.0, 0.80 * exact + brand_bonus + category_bonus + provenance_bonus)
        reasons = ["exact_cross_modal_similarity", "approved", "policy_allowed"]
        if brand_bonus:
            reasons.append("brand_match")
        if category_bonus:
            reasons.append("category_match")
        scored.append((score, candidate, tuple(reasons)))
    scored.sort(key=lambda item: (-item[0], item[1].record.id))

    selected: list[SearchResult] = []
    seen_sources: set[tuple[str, str | None]] = set()
    while scored and len(selected) < limit:
        best_index = 0
        best_adjusted = -1.0
        for index, (score, result, _) in enumerate(scored):
            source_key = (result.record.source_type, result.record.campaign_id)
            diversity_penalty = 0.05 if source_key in seen_sources else 0.0
            adjusted = score - diversity_penalty
            if adjusted > best_adjusted:
                best_adjusted = adjusted
                best_index = index
        _, result, result_reasons = scored.pop(best_index)
        seen_sources.add((result.record.source_type, result.record.campaign_id))
        selected.append(
            SearchResult(
                record=result.record,
                similarity=result.similarity,
                rerank_score=round(max(0.0, best_adjusted), 6),
                rank=len(selected) + 1,
                reasons=result_reasons,
            )
        )
    return selected


def _campaign_category(campaign: Campaign) -> str:
    objective = campaign.brief.objective.lower()
    for category in ("launch", "awareness", "conversion", "retention", "event"):
        if category in objective:
            return category
    return "general"


def _extract_text(content: bytes, media_type: str) -> str:
    if media_type == "text/plain":
        return content.decode("utf-8")
    try:
        from pypdf import PdfReader
    except ImportError as error:
        raise ValidationError("PDF indexing requires pypdf") from error
    try:
        reader = PdfReader(io.BytesIO(content), strict=True)
    except Exception as error:
        raise ValidationError("PDF could not be parsed for retrieval indexing") from error
    if len(reader.pages) > MAX_PDF_PAGES:
        raise ValidationError(f"PDF exceeds the {MAX_PDF_PAGES}-page indexing limit")
    return "\n\n".join((page.extract_text() or "") for page in reader.pages)


def _chunks(text: str) -> list[str]:
    normalized = " ".join(text.split())
    if not normalized:
        return []
    chunks: list[str] = []
    position = 0
    while position < len(normalized) and len(chunks) < MAX_CHUNKS_PER_ASSET:
        end = min(len(normalized), position + CHUNK_CHARACTERS)
        if end < len(normalized):
            boundary = normalized.rfind(" ", position, end)
            if boundary > position + CHUNK_CHARACTERS // 2:
                end = boundary
        chunks.append(normalized[position:end])
        if end == len(normalized):
            break
        position = max(position + 1, end - CHUNK_OVERLAP)
    return chunks


def _media_type_for_object_key(key: str) -> str:
    suffix = key.rsplit(".", 1)[-1].lower() if "." in key else ""
    return {
        "png": "image/png",
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
        "webp": "image/webp",
        "svg": "image/svg+xml",
    }.get(suffix, "application/octet-stream")


def result_payload(result: SearchResult) -> dict[str, Any]:
    record = result.record
    return {
        "id": record.id,
        "source_type": record.source_type,
        "source_id": record.source_id,
        "modality": record.modality.value,
        "content": record.content,
        "object_key": record.object_key,
        "asset_kind": record.asset_kind.value if isinstance(record.asset_kind, AssetKind) else None,
        "media_type": record.media_type,
        "brand": record.brand,
        "campaign_category": record.campaign_category,
        "similarity": round(result.similarity, 6),
        "rerank_score": result.rerank_score,
        "rank": result.rank,
        "reasons": list(result.reasons),
        "provenance": {
            "source_hash": record.source_hash,
            "campaign_id": record.campaign_id,
            "asset_id": record.asset_id,
            "model": record.embedding_model,
            "model_version": record.embedding_model_version,
        },
    }


def summary_payload(summary: IndexingSummary | RetrievalStatusSummary) -> dict[str, Any]:
    return asdict(summary)
