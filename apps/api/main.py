from __future__ import annotations

import base64
import binascii
from collections.abc import Awaitable, Callable
from dataclasses import asdict
from pathlib import PurePosixPath
from typing import Annotated, Any
from uuid import uuid4

from fastapi import FastAPI, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response

from brandforge import __version__
from brandforge.config import Settings
from brandforge.domain import ApprovalDecision, AssetRecord, CampaignBrief
from brandforge.editor import DesignSnapshot
from brandforge.exceptions import (
    BrandForgeError,
    ConcurrencyError,
    InvalidTransitionError,
    NotFoundError,
    SecurityError,
    TenantIsolationError,
    ValidationError,
)
from brandforge.factory import build_workflow
from brandforge.ingestion import extract_document
from brandforge.preference_dataset import (
    CuratedComparison,
    build_comparisons,
    dataset_fingerprint,
)
from brandforge.retrieval_service import result_payload, summary_payload
from brandforge.security import validate_upload
from brandforge.telemetry import configure_logging, metrics, trace_id_var

from .dependencies import Tenant, Workflow
from .schemas import (
    ApprovalRequest,
    AssetUploadResponse,
    BrandGuideRequest,
    CampaignListResponse,
    CampaignResponse,
    CancelRequest,
    CreateCampaignRequest,
    CuratePreferenceRequest,
    DesignResponse,
    DesignRevisionResponse,
    ErrorResponse,
    EventListResponse,
    HealthResponse,
    LayerDocumentResponse,
    PreferenceDatasetImportRequest,
    PreferenceDatasetResponse,
    RetrievalBackfillResponse,
    RetrievalSearchResponse,
    RetrievalStatusResponse,
    RetrievalTextRequest,
    SaveDesignRequest,
    SelectionRequest,
)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    configure_logging(settings.log_level)
    app = FastAPI(
        title="BrandForge API",
        version=__version__,
        description="Human-guided, brand-safe campaign generation and multimodal reranking.",
        docs_url="/docs" if settings.environment != "production" else None,
        redoc_url=None,
    )
    app.state.settings = settings
    app.state.workflow = build_workflow(settings)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.allowed_origins),
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT"],
        allow_headers=[
            "Content-Type",
            "X-Tenant-ID",
            "X-User-ID",
            "X-User-Role",
            "X-Idempotency-Key",
        ],
    )
    _register_exception_handlers(app)
    _register_routes(app)
    return app


def _register_routes(app: FastAPI) -> None:
    @app.middleware("http")
    async def trace_middleware(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        incoming = request.headers.get("x-trace-id", "")
        trace_id = incoming if _valid_trace_id(incoming) else uuid4().hex
        token = trace_id_var.set(trace_id)
        try:
            response = await call_next(request)
            response.headers["X-Trace-ID"] = trace_id
            response.headers["X-Content-Type-Options"] = "nosniff"
            response.headers["Referrer-Policy"] = "no-referrer"
            return response
        finally:
            trace_id_var.reset(token)

    @app.get("/", include_in_schema=False)
    def root() -> dict[str, str]:
        return {"name": "BrandForge", "docs": "/docs", "health": "/health/ready"}

    @app.get("/health/live", response_model=HealthResponse)
    def live() -> HealthResponse:
        return HealthResponse(status="ok", version=__version__)

    @app.get("/health/ready", response_model=HealthResponse)
    def ready(workflow: Workflow) -> HealthResponse:
        del workflow
        return HealthResponse(status="ok", version=__version__)

    @app.get("/metrics", response_class=Response)
    def prometheus_metrics() -> Response:
        return Response(metrics.render_prometheus(), media_type="text/plain; version=0.0.4")

    @app.post("/v1/campaigns", response_model=CampaignResponse, status_code=201)
    def create_campaign(
        body: CreateCampaignRequest,
        context: Tenant,
        workflow: Workflow,
        idempotency_key: Annotated[str | None, Header(alias="X-Idempotency-Key")] = None,
    ) -> CampaignResponse:
        repository = workflow.repository
        if idempotency_key and hasattr(repository, "idempotency_get"):
            cached = repository.idempotency_get(context.tenant_id, idempotency_key)
            if cached:
                return CampaignResponse(campaign=cached["campaign"])
        campaign = workflow.create_campaign(
            context.tenant_id,
            body.name,
            CampaignBrief(**body.brief.model_dump()),
        )
        if body.brand_guide_text:
            campaign = workflow.compile_brand_guide(
                context.tenant_id, campaign.id, body.brand_guide_text
            )
        response = CampaignResponse(campaign=campaign.to_dict())
        if idempotency_key and hasattr(repository, "idempotency_put"):
            repository.idempotency_put(context.tenant_id, idempotency_key, response.model_dump())
        return response

    @app.get("/v1/campaigns", response_model=CampaignListResponse)
    def list_campaigns(context: Tenant, workflow: Workflow) -> CampaignListResponse:
        return CampaignListResponse(
            campaigns=[item.to_dict() for item in workflow.list_campaigns(context.tenant_id)]
        )

    @app.get("/v1/campaigns/{campaign_id}", response_model=CampaignResponse)
    def get_campaign(campaign_id: str, context: Tenant, workflow: Workflow) -> CampaignResponse:
        return CampaignResponse(
            campaign=workflow.get_campaign(context.tenant_id, campaign_id).to_dict()
        )

    @app.post("/v1/campaigns/{campaign_id}/brand-guide", response_model=CampaignResponse)
    def compile_brand_guide(
        campaign_id: str,
        body: BrandGuideRequest,
        context: Tenant,
        workflow: Workflow,
    ) -> CampaignResponse:
        campaign = workflow.compile_brand_guide(context.tenant_id, campaign_id, body.text)
        return CampaignResponse(campaign=campaign.to_dict())

    @app.post(
        "/v1/campaigns/{campaign_id}/assets",
        response_model=AssetUploadResponse,
        status_code=201,
    )
    async def upload_asset(
        campaign_id: str,
        context: Tenant,
        file: Annotated[UploadFile, File()],
        workflow: Workflow,
        kind: Annotated[str, Form()] = "product_asset",
    ) -> AssetUploadResponse:
        if kind not in {"brand_guide", "product_asset", "logo", "approved_example"}:
            raise HTTPException(status_code=422, detail="unsupported asset kind")
        content = await file.read(app.state.settings.max_upload_bytes + 1)
        upload = validate_upload(
            file.filename or "upload",
            content,
            file.content_type,
            app.state.settings.max_upload_bytes,
        )
        workflow.get_campaign(context.tenant_id, campaign_id)
        key = f"raw/{context.tenant_id}/{campaign_id}/{upload.sha256[:16]}/{upload.filename}"
        workflow.exporter.object_store.put(key, upload.content, upload.media_type)
        asset = AssetRecord(
            id=f"ast_{uuid4().hex[:16]}",
            object_key=key,
            filename=upload.filename,
            media_type=upload.media_type,
            sha256=upload.sha256,
            size_bytes=upload.size_bytes,
            kind=kind,
        )
        campaign = workflow.attach_asset(context.tenant_id, campaign_id, asset)
        if kind == "brand_guide":
            extracted = extract_document(upload)
            if extracted.text.strip():
                campaign = workflow.compile_brand_guide(
                    context.tenant_id, campaign_id, extracted.text
                )
        return AssetUploadResponse(asset=asdict(asset), campaign=campaign.to_dict())

    @app.post(
        "/v1/campaigns/{campaign_id}/approvals/brand-rules",
        response_model=CampaignResponse,
    )
    def review_brand_rules(
        campaign_id: str,
        body: ApprovalRequest,
        context: Tenant,
        workflow: Workflow,
    ) -> CampaignResponse:
        campaign = workflow.review_brand_rules(
            context.tenant_id,
            campaign_id,
            context.user_id,
            context.role,
            ApprovalDecision(body.decision),
            body.comments,
            body.corrections,
            body.reason_codes,
        )
        return CampaignResponse(campaign=campaign.to_dict())

    @app.post("/v1/campaigns/{campaign_id}/approvals/plan", response_model=CampaignResponse)
    def review_plan(
        campaign_id: str,
        body: ApprovalRequest,
        context: Tenant,
        workflow: Workflow,
    ) -> CampaignResponse:
        campaign = workflow.review_plan(
            context.tenant_id,
            campaign_id,
            context.user_id,
            context.role,
            ApprovalDecision(body.decision),
            body.comments,
            body.reason_codes,
        )
        return CampaignResponse(campaign=campaign.to_dict())

    @app.post("/v1/campaigns/{campaign_id}/selection", response_model=CampaignResponse)
    def select_variant(
        campaign_id: str,
        body: SelectionRequest,
        context: Tenant,
        workflow: Workflow,
    ) -> CampaignResponse:
        campaign = workflow.select_variant(
            context.tenant_id,
            campaign_id,
            context.user_id,
            context.role,
            body.variant_id,
            body.reason_code,
            body.explanation,
        )
        return CampaignResponse(campaign=campaign.to_dict())

    @app.post(
        "/v1/campaigns/{campaign_id}/retrieval/text",
        response_model=RetrievalSearchResponse,
    )
    def retrieval_text(
        campaign_id: str,
        body: RetrievalTextRequest,
        context: Tenant,
        workflow: Workflow,
    ) -> RetrievalSearchResponse:
        results = workflow.search_retrieval_text(
            context.tenant_id,
            campaign_id,
            body.query,
            limit=body.limit,
        )
        service = workflow.retrieval
        assert service is not None
        return RetrievalSearchResponse(
            campaign_id=campaign_id,
            query_modality="text",
            model=service.embeddings.model_name,
            model_version=service.embeddings.model_version,
            synthetic=service.synthetic,
            results=[result_payload(item) for item in results],
        )

    @app.post(
        "/v1/campaigns/{campaign_id}/retrieval/image",
        response_model=RetrievalSearchResponse,
    )
    async def retrieval_image(
        campaign_id: str,
        context: Tenant,
        file: Annotated[UploadFile, File()],
        workflow: Workflow,
        limit: Annotated[int, Form(ge=1, le=20)] = 10,
    ) -> RetrievalSearchResponse:
        content = await file.read(app.state.settings.max_upload_bytes + 1)
        upload = validate_upload(
            file.filename or "query-image",
            content,
            file.content_type,
            app.state.settings.max_upload_bytes,
        )
        if upload.media_type not in {"image/png", "image/jpeg"}:
            raise ValidationError("retrieval image must be a PNG or JPEG")
        results = workflow.search_retrieval_image(
            context.tenant_id,
            campaign_id,
            upload.content,
            limit=limit,
        )
        service = workflow.retrieval
        assert service is not None
        return RetrievalSearchResponse(
            campaign_id=campaign_id,
            query_modality="image",
            model=service.embeddings.model_name,
            model_version=service.embeddings.model_version,
            synthetic=service.synthetic,
            results=[result_payload(item) for item in results],
        )

    @app.get(
        "/v1/campaigns/{campaign_id}/retrieval/status",
        response_model=RetrievalStatusResponse,
    )
    def retrieval_status(
        campaign_id: str,
        context: Tenant,
        workflow: Workflow,
    ) -> RetrievalStatusResponse:
        summary = workflow.retrieval_status(context.tenant_id, campaign_id)
        return RetrievalStatusResponse.model_validate(summary_payload(summary))

    @app.post(
        "/v1/campaigns/{campaign_id}/retrieval/backfill",
        response_model=RetrievalBackfillResponse,
    )
    def retrieval_backfill(
        campaign_id: str,
        context: Tenant,
        workflow: Workflow,
    ) -> RetrievalBackfillResponse:
        if context.role not in {"campaign_owner", "admin", "retrieval_curator"}:
            raise HTTPException(status_code=403, detail="retrieval backfill requires curator role")
        summaries = workflow.backfill_retrieval(context.tenant_id, campaign_id)
        return RetrievalBackfillResponse(
            summaries=[summary_payload(summary) for summary in summaries]
        )

    @app.post(
        "/v1/campaigns/{campaign_id}/preferences/{feedback_id}/curate",
        response_model=CampaignResponse,
    )
    def curate_preference(
        campaign_id: str,
        feedback_id: str,
        body: CuratePreferenceRequest,
        context: Tenant,
        workflow: Workflow,
    ) -> CampaignResponse:
        if context.role not in {
            "campaign_owner",
            "admin",
            "reviewer",
            "preference_curator",
        }:
            raise HTTPException(
                status_code=403,
                detail="preference curation requires reviewer role",
            )
        campaign = workflow.curate_preference_feedback(
            context.tenant_id,
            campaign_id,
            feedback_id,
            curator_id=context.user_id,
            curation_status=body.status,
            dataset_version=body.dataset_version,
        )
        return CampaignResponse(campaign=campaign.to_dict())

    @app.get("/v1/preference-datasets/{dataset_version}", response_model=PreferenceDatasetResponse)
    def export_preference_dataset(
        dataset_version: str,
        context: Tenant,
        workflow: Workflow,
    ) -> PreferenceDatasetResponse:
        rows = [
            row
            for campaign in workflow.list_campaigns(context.tenant_id)
            for row in build_comparisons(campaign)
            if row.dataset_version == dataset_version
        ]
        return PreferenceDatasetResponse(
            dataset_version=dataset_version,
            tenant_id=context.tenant_id,
            row_count=len(rows),
            fingerprint=dataset_fingerprint(rows),
            rows=[row.to_dict() for row in rows],
            synthetic=any(row.synthetic for row in rows),
        )

    @app.post("/v1/preference-datasets/import", response_model=PreferenceDatasetResponse)
    def import_preference_dataset(
        body: PreferenceDatasetImportRequest,
        context: Tenant,
        workflow: Workflow,
    ) -> PreferenceDatasetResponse:
        if context.role not in {"campaign_owner", "admin", "preference_curator"}:
            raise HTTPException(status_code=403, detail="preference import requires curator role")
        try:
            rows = [CuratedComparison.from_dict(row) for row in body.rows]
        except ValueError as error:
            raise ValidationError(str(error)) from error
        grouped_rows: dict[tuple[str, str], list[CuratedComparison]] = {}
        for row in rows:
            if row.tenant_id != context.tenant_id:
                raise ValidationError("preference import contains a cross-tenant row")
            if row.dataset_version != body.dataset_version:
                raise ValidationError("preference import contains a different dataset version")
            grouped_rows.setdefault((row.campaign_id, row.feedback_id), []).append(row)
        touched_campaigns: set[str] = set()
        for (campaign_id, feedback_id), feedback_rows in grouped_rows.items():
            campaign = workflow.get_campaign(context.tenant_id, campaign_id)
            feedback = next(
                (item for item in campaign.feedback if item.id == feedback_id),
                None,
            )
            if feedback is None:
                raise ValidationError("preference import references unknown campaign feedback")
            if {item.rejected_variant_id for item in feedback_rows} != set(
                feedback.rejected_variant_ids
            ):
                raise ValidationError("preference import must contain every frozen rejected pair")
            for item in feedback_rows:
                if (
                    item.preferred_variant_id != feedback.preferred_variant_id
                    or item.preferred_features != feedback.preferred_features
                    or item.rejected_features
                    != feedback.rejected_features[item.rejected_variant_id]
                    or item.brief_fingerprint != feedback.brief_fingerprint
                    or item.presentation_order != tuple(feedback.presentation_order)
                ):
                    raise ValidationError(
                        "preference import does not match the frozen selection snapshot"
                    )
            if not feedback.curated or feedback.dataset_version != body.dataset_version:
                campaign = workflow.curate_preference_feedback(
                    context.tenant_id,
                    campaign_id,
                    feedback_id,
                    curator_id=context.user_id,
                    curation_status="curated",
                    dataset_version=body.dataset_version,
                )
            touched_campaigns.add(campaign.id)
        persisted_rows = [
            row
            for campaign_id in sorted(touched_campaigns)
            for row in build_comparisons(
                workflow.get_campaign(context.tenant_id, campaign_id)
            )
            if row.dataset_version == body.dataset_version
        ]
        return PreferenceDatasetResponse(
            dataset_version=body.dataset_version,
            tenant_id=context.tenant_id,
            row_count=len(persisted_rows),
            fingerprint=dataset_fingerprint(persisted_rows),
            rows=[row.to_dict() for row in persisted_rows],
            synthetic=any(row.synthetic for row in persisted_rows),
        )

    @app.post("/v1/campaigns/{campaign_id}/approvals/final", response_model=CampaignResponse)
    def review_final(
        campaign_id: str,
        body: ApprovalRequest,
        context: Tenant,
        workflow: Workflow,
    ) -> CampaignResponse:
        campaign = workflow.review_final(
            context.tenant_id,
            campaign_id,
            context.user_id,
            context.role,
            ApprovalDecision(body.decision),
            body.comments,
            body.reason_codes,
        )
        return CampaignResponse(campaign=campaign.to_dict())

    @app.get(
        "/v1/campaigns/{campaign_id}/designs/{channel}",
        response_model=DesignResponse,
    )
    def get_design(
        campaign_id: str,
        channel: str,
        context: Tenant,
        workflow: Workflow,
    ) -> DesignResponse:
        snapshot = workflow.load_design(context.tenant_id, campaign_id, channel)
        campaign = workflow.get_campaign(context.tenant_id, campaign_id)
        return _design_response(campaign.to_dict(), snapshot)

    @app.put(
        "/v1/campaigns/{campaign_id}/designs/{channel}",
        response_model=DesignResponse,
    )
    def save_design(
        campaign_id: str,
        channel: str,
        body: SaveDesignRequest,
        context: Tenant,
        workflow: Workflow,
    ) -> DesignResponse:
        if body.channel is not None and body.channel != channel:
            raise ValidationError("request channel does not match the route")
        if (
            body.layer_document.channel is not None
            and body.layer_document.channel != channel
        ):
            raise ValidationError("layer document channel does not match the route")
        preview_png: bytes | None = None
        if body.preview_png_base64 is not None:
            try:
                preview_png = base64.b64decode(body.preview_png_base64, validate=True)
            except (binascii.Error, ValueError) as error:
                raise ValidationError("preview must be valid base64") from error
        document = body.layer_document.model_dump()
        document["channel"] = channel
        campaign = workflow.save_design(
            context.tenant_id,
            campaign_id,
            channel,
            layer_document=document,
            fabric_json=body.fabric_json,
            svg=body.svg,
            preview_png=preview_png,
            expected_revision=body.expected_revision,
            created_by=context.user_id,
            editor="fabric",
            editor_version=body.editor_version,
        )
        snapshot = workflow.load_design(context.tenant_id, campaign_id, channel)
        return _design_response(campaign.to_dict(), snapshot)

    @app.get("/v1/campaigns/{campaign_id}/designs/{channel}/preview")
    def design_preview(
        campaign_id: str,
        channel: str,
        context: Tenant,
        workflow: Workflow,
    ) -> Response:
        snapshot = workflow.load_design(context.tenant_id, campaign_id, channel)
        if snapshot.preview_png is None:
            raise NotFoundError("design preview is unavailable")
        return Response(
            snapshot.preview_png,
            media_type="image/png",
            headers={"Cache-Control": "private, no-store"},
        )

    @app.get("/v1/campaigns/{campaign_id}/events", response_model=EventListResponse)
    def events(campaign_id: str, context: Tenant, workflow: Workflow) -> EventListResponse:
        return EventListResponse(
            events=[asdict(item) for item in workflow.events(context.tenant_id, campaign_id)]
        )

    @app.get("/v1/campaigns/{campaign_id}/variants/{variant_id}/image")
    def variant_image(
        campaign_id: str,
        variant_id: str,
        context: Tenant,
        workflow: Workflow,
    ) -> Response:
        campaign = workflow.get_campaign(context.tenant_id, campaign_id)
        variant = next((item for item in campaign.variants if item.id == variant_id), None)
        if not variant or not variant.asset_object_key:
            raise NotFoundError("generated image is unavailable")
        content = workflow.exporter.object_store.get(variant.asset_object_key)
        media_type = _media_type_for_key(variant.asset_object_key)
        return Response(
            content,
            media_type=media_type,
            headers={
                "Cache-Control": "private, max-age=60",
                "Content-Security-Policy": "sandbox; default-src 'none'",
            },
        )

    @app.get("/v1/campaigns/{campaign_id}/exports/{artifact}")
    def download_export(
        campaign_id: str,
        artifact: str,
        context: Tenant,
        workflow: Workflow,
    ) -> Response:
        campaign = workflow.get_campaign(context.tenant_id, campaign_id)
        if campaign.export is None:
            raise NotFoundError("campaign export is unavailable")
        available = {"manifest": campaign.export.object_key, **campaign.export.formats}
        key = available.get(artifact)
        if key is None:
            raise NotFoundError("export artifact is unavailable")
        content = workflow.exporter.object_store.get(key)
        suffix = PurePosixPath(key).suffix.lower()
        filename = f"{campaign.id}-{artifact}{suffix}"
        return Response(
            content,
            media_type=_media_type_for_key(key),
            headers={
                "Cache-Control": "private, no-store",
                "Content-Disposition": f'attachment; filename="{filename}"',
                "Content-Security-Policy": "sandbox; default-src 'none'",
            },
        )

    @app.post("/v1/campaigns/{campaign_id}/cancel", response_model=CampaignResponse)
    def cancel(
        campaign_id: str,
        body: CancelRequest,
        context: Tenant,
        workflow: Workflow,
    ) -> CampaignResponse:
        del body
        campaign = workflow.cancel(context.tenant_id, campaign_id, context.user_id)
        return CampaignResponse(campaign=campaign.to_dict())


def _register_exception_handlers(app: FastAPI) -> None:
    status_map = {
        NotFoundError: 404,
        TenantIsolationError: 404,
        InvalidTransitionError: 409,
        ConcurrencyError: 409,
        ValidationError: 422,
        SecurityError: 400,
    }

    @app.exception_handler(BrandForgeError)
    async def brandforge_error(_: Request, error: BrandForgeError) -> JSONResponse:
        status_code = next(
            (status for kind, status in status_map.items() if isinstance(error, kind)), 400
        )
        body = ErrorResponse(
            error=type(error).__name__, message=str(error), trace_id=trace_id_var.get() or None
        )
        return JSONResponse(status_code=status_code, content=body.model_dump())


def _valid_trace_id(value: str) -> bool:
    return (
        bool(value) and len(value) <= 64 and all(char.isalnum() or char in "-_" for char in value)
    )


def _design_response(campaign: dict[str, Any], snapshot: DesignSnapshot) -> DesignResponse:
    revision = asdict(snapshot.revision) if snapshot.revision is not None else None
    document = asdict(snapshot.layer_document)
    return DesignResponse(
        campaign_id=str(campaign["id"]),
        campaign_version=int(campaign["version"]),
        revision=snapshot.revision.revision if snapshot.revision is not None else 0,
        revision_metadata=(
            DesignRevisionResponse.model_validate(revision) if revision is not None else None
        ),
        layer_document=LayerDocumentResponse.model_validate(document),
        fabric_json=snapshot.fabric_json,
        svg=snapshot.svg,
        campaign=campaign,
    )


def _media_type_for_key(key: str) -> str:
    suffix = PurePosixPath(key).suffix.lower()
    return {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
        ".svg": "image/svg+xml",
        ".json": "application/json",
    }.get(suffix, "application/octet-stream")


app = create_app()
