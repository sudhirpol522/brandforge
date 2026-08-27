from __future__ import annotations

from pathlib import Path

from .agents import BrandCompilerAgent, CampaignPlannerAgent, CreativeAgent, MultimodalReranker
from .agents.preferences import PairwisePreferenceModel
from .config import Settings
from .editor import DesignEditor
from .exporter import CampaignExporter
from .model_gateway import (
    DeterministicModelProvider,
    ModelGateway,
    ModelProvider,
    OpenAICompatibleProvider,
)
from .object_store import LocalObjectStore
from .persistence import SQLiteCampaignRepository
from .ports import CampaignRepository, EmbeddingProvider, ObjectStore, RetrievalRepository
from .retrieval_service import MultimodalRetrievalService
from .workflow import BrandForgeWorkflow


def build_workflow(settings: Settings | None = None) -> BrandForgeWorkflow:
    settings = settings or Settings.from_env()
    repository = build_repository(settings)
    object_store = _build_object_store(settings)
    provider = _build_model_provider(settings)
    gateway = ModelGateway(
        provider,
        max_calls_per_campaign=settings.model_max_calls_per_campaign,
        max_cost_per_campaign_usd=settings.model_request_budget_usd,
    )
    exporter = CampaignExporter(object_store)
    retrieval_service = None
    if settings.retrieval_enabled:
        embeddings = build_embedding_provider(settings)
        retrieval_service = MultimodalRetrievalService(
            campaigns=repository,
            repository=build_retrieval_repository(settings),
            embeddings=embeddings,
            object_store=object_store,
            candidate_limit=settings.retrieval_candidate_limit,
        )
    preference_model = PairwisePreferenceModel()
    if settings.preference_model_path:
        preference_model = PairwisePreferenceModel.load(settings.preference_model_path)
    return BrandForgeWorkflow(
        repository=repository,
        brand_compiler=BrandCompilerAgent(),
        planner=CampaignPlannerAgent(),
        creative=CreativeAgent(gateway),
        reranker=MultimodalReranker(preference_model=preference_model),
        exporter=exporter,
        editor=DesignEditor(object_store),
        retrieval=retrieval_service,
    )


def build_repository(settings: Settings) -> CampaignRepository:
    if settings.database_url.startswith("sqlite:///"):
        path = settings.database_url.removeprefix("sqlite:///")
        return SQLiteCampaignRepository(Path(path))
    from .integrations.sqlalchemy_repository import SQLAlchemyCampaignRepository

    return SQLAlchemyCampaignRepository(settings.database_url)


def build_retrieval_repository(settings: Settings) -> RetrievalRepository:
    from .integrations.retrieval_repository import (
        PostgreSQLRetrievalRepository,
        SQLiteRetrievalRepository,
    )

    if settings.database_url.startswith("sqlite:///"):
        path = settings.database_url.removeprefix("sqlite:///")
        return SQLiteRetrievalRepository(Path(path))
    return PostgreSQLRetrievalRepository(
        settings.database_url,
        dimension=settings.retrieval_embedding_dimension,
    )


def build_embedding_provider(settings: Settings) -> EmbeddingProvider:
    from .integrations.clip_scorer import (
        DeterministicEmbeddingProvider,
        OpenCLIPEmbeddingProvider,
        RemoteEmbeddingProvider,
    )

    if settings.retrieval_embedding_provider == "deterministic":
        return DeterministicEmbeddingProvider(
            dimension=settings.retrieval_embedding_dimension
        )
    if settings.retrieval_embedding_provider in {"openclip", "clip", "siglip"}:
        return OpenCLIPEmbeddingProvider(
            model_name=settings.retrieval_model_name,
            pretrained=settings.retrieval_model_version,
            expected_dimension=settings.retrieval_embedding_dimension,
            device=settings.retrieval_device,
        )
    if settings.retrieval_embedding_provider == "remote":
        if not settings.retrieval_remote_url:
            raise ValueError(
                "RETRIEVAL_REMOTE_URL is required for the remote embedding provider"
            )
        return RemoteEmbeddingProvider(
            base_url=settings.retrieval_remote_url,
            model_name=settings.retrieval_model_name,
            model_version=settings.retrieval_model_version,
            dimension=settings.retrieval_embedding_dimension,
            token=settings.retrieval_worker_token,
        )
    raise ValueError(
        "RETRIEVAL_EMBEDDING_PROVIDER must be deterministic, remote, openclip, clip, or siglip"
    )


def _build_object_store(settings: Settings) -> ObjectStore:
    if settings.object_store_provider == "local":
        return LocalObjectStore(settings.local_object_store_path)
    if settings.object_store_provider == "s3":
        from .integrations.s3_store import S3ObjectStore

        return S3ObjectStore(
            bucket=settings.s3_bucket,
            endpoint_url=settings.s3_endpoint_url,
            region=settings.s3_region,
            access_key_id=settings.s3_access_key_id,
            secret_access_key=settings.s3_secret_access_key,
        )
    raise ValueError(f"unsupported object store: {settings.object_store_provider}")


def _build_model_provider(settings: Settings) -> ModelProvider:
    if settings.adobe_firefly_enabled:
        from .integrations.adobe_firefly import AdobeFireflyProvider

        return AdobeFireflyProvider.from_env()
    if settings.model_provider == "deterministic":
        return DeterministicModelProvider()
    if settings.model_provider == "openai":
        if not settings.openai_api_key:
            raise ValueError("OPENAI_API_KEY is required when MODEL_PROVIDER=openai")
        from .integrations.openai_provider import OpenAIResponsesProvider

        return OpenAIResponsesProvider(
            api_key=settings.openai_api_key,
            text_model=settings.openai_text_model,
            vision_model=settings.openai_vision_model,
            image_model=settings.openai_image_model,
            base_url=settings.openai_base_url,
            reasoning_effort=settings.openai_reasoning_effort,
            text_max_output_tokens=settings.openai_text_max_output_tokens,
            vision_max_output_tokens=settings.openai_vision_max_output_tokens,
            text_cost_usd=settings.openai_estimated_text_call_usd,
            vision_cost_usd=settings.openai_estimated_vision_call_usd,
            image_cost_usd=settings.openai_estimated_image_call_usd,
        )
    if settings.model_provider == "openai-compatible":
        if not settings.openai_base_url or not settings.openai_api_key:
            raise ValueError("OPENAI_BASE_URL and OPENAI_API_KEY are required")
        return OpenAICompatibleProvider(
            settings.openai_base_url, settings.openai_api_key, settings.openai_text_model
        )
    raise ValueError(f"unsupported model provider: {settings.model_provider}")
