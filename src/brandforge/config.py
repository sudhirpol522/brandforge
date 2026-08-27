from __future__ import annotations

import os
from dataclasses import dataclass
from urllib.parse import quote_plus


def _as_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True, slots=True)
class Settings:
    environment: str = "development"
    log_level: str = "INFO"
    database_url: str = "sqlite:///./data/brandforge.db"
    object_store_provider: str = "local"
    local_object_store_path: str = "./data/objects"
    s3_endpoint_url: str | None = None
    s3_bucket: str = "brandforge-assets"
    s3_access_key_id: str | None = None
    s3_secret_access_key: str | None = None
    s3_region: str = "us-east-1"
    model_provider: str = "deterministic"
    openai_api_key: str | None = None
    openai_base_url: str | None = None
    openai_text_model: str = "gpt-5.6"
    openai_vision_model: str = "gpt-5.6"
    openai_image_model: str = "gpt-image-2"
    openai_reasoning_effort: str | None = "none"
    openai_text_max_output_tokens: int = 1024
    openai_vision_max_output_tokens: int = 1024
    openai_estimated_text_call_usd: float = 0.01
    openai_estimated_vision_call_usd: float = 0.015
    openai_estimated_image_call_usd: float = 0.05
    model_request_budget_usd: float = 5.0
    model_max_calls_per_campaign: int = 50
    dev_auth: bool = True
    default_tenant: str = "demo-studio"
    default_user: str = "creative-director"
    max_upload_bytes: int = 25 * 1024 * 1024
    allowed_origins: tuple[str, ...] = ("http://localhost:3000",)
    adobe_firefly_enabled: bool = False
    orchestrator: str = "inline"
    temporal_address: str = "temporal:7233"
    temporal_namespace: str = "default"
    temporal_task_queue: str = "brandforge-general"
    retrieval_enabled: bool = False
    retrieval_embedding_provider: str = "deterministic"
    retrieval_model_name: str = "ViT-B-32"
    retrieval_model_version: str = "laion2b_s34b_b79k"
    retrieval_embedding_dimension: int = 32
    retrieval_device: str = "cpu"
    retrieval_candidate_limit: int = 50
    retrieval_remote_url: str | None = None
    retrieval_worker_token: str | None = None
    preference_model_path: str | None = None

    @classmethod
    def from_env(cls) -> Settings:
        return cls(
            environment=os.getenv("BRANDFORGE_ENV", "development"),
            log_level=os.getenv("BRANDFORGE_LOG_LEVEL", "INFO"),
            database_url=_database_url(),
            object_store_provider=os.getenv("OBJECT_STORE_PROVIDER", "local"),
            local_object_store_path=os.getenv("LOCAL_OBJECT_STORE_PATH", "./data/objects"),
            s3_endpoint_url=os.getenv("S3_ENDPOINT_URL"),
            s3_bucket=os.getenv("S3_BUCKET", "brandforge-assets"),
            s3_access_key_id=os.getenv("S3_ACCESS_KEY_ID"),
            s3_secret_access_key=os.getenv("S3_SECRET_ACCESS_KEY"),
            s3_region=os.getenv("S3_REGION", "us-east-1"),
            model_provider=os.getenv("MODEL_PROVIDER", "deterministic"),
            openai_api_key=os.getenv("OPENAI_API_KEY"),
            openai_base_url=os.getenv("OPENAI_BASE_URL"),
            openai_text_model=os.getenv("OPENAI_TEXT_MODEL", "gpt-5.6"),
            openai_vision_model=os.getenv("OPENAI_VISION_MODEL", "gpt-5.6"),
            openai_image_model=os.getenv("OPENAI_IMAGE_MODEL", "gpt-image-2"),
            openai_reasoning_effort=(
                os.getenv("OPENAI_REASONING_EFFORT", "none").strip() or None
            ),
            openai_text_max_output_tokens=int(
                os.getenv("OPENAI_TEXT_MAX_OUTPUT_TOKENS", "1024")
            ),
            openai_vision_max_output_tokens=int(
                os.getenv("OPENAI_VISION_MAX_OUTPUT_TOKENS", "1024")
            ),
            openai_estimated_text_call_usd=float(
                os.getenv("OPENAI_ESTIMATED_TEXT_CALL_USD", "0.01")
            ),
            openai_estimated_vision_call_usd=float(
                os.getenv("OPENAI_ESTIMATED_VISION_CALL_USD", "0.015")
            ),
            openai_estimated_image_call_usd=float(
                os.getenv("OPENAI_ESTIMATED_IMAGE_CALL_USD", "0.05")
            ),
            model_request_budget_usd=float(os.getenv("MODEL_REQUEST_BUDGET_USD", "5")),
            model_max_calls_per_campaign=int(os.getenv("MODEL_MAX_CALLS_PER_CAMPAIGN", "50")),
            dev_auth=_as_bool(os.getenv("BRANDFORGE_DEV_AUTH"), True),
            default_tenant=os.getenv("BRANDFORGE_DEFAULT_TENANT", "demo-studio"),
            default_user=os.getenv("BRANDFORGE_DEFAULT_USER", "creative-director"),
            max_upload_bytes=int(os.getenv("MAX_UPLOAD_BYTES", str(25 * 1024 * 1024))),
            allowed_origins=tuple(
                item.strip()
                for item in os.getenv("ALLOWED_ORIGINS", "http://localhost:3000").split(",")
                if item.strip()
            ),
            adobe_firefly_enabled=_as_bool(os.getenv("ADOBE_FIREFLY_ENABLED"), False),
            orchestrator=os.getenv("ORCHESTRATOR", "inline"),
            temporal_address=os.getenv("TEMPORAL_ADDRESS", "temporal:7233"),
            temporal_namespace=os.getenv("TEMPORAL_NAMESPACE", "default"),
            temporal_task_queue=os.getenv("TEMPORAL_TASK_QUEUE", "brandforge-general"),
            retrieval_enabled=_as_bool(os.getenv("RETRIEVAL_ENABLED"), False),
            retrieval_embedding_provider=os.getenv(
                "RETRIEVAL_EMBEDDING_PROVIDER", "deterministic"
            ),
            retrieval_model_name=os.getenv("RETRIEVAL_MODEL_NAME", "ViT-B-32"),
            retrieval_model_version=os.getenv(
                "RETRIEVAL_MODEL_VERSION", "laion2b_s34b_b79k"
            ),
            retrieval_embedding_dimension=int(
                os.getenv("RETRIEVAL_EMBEDDING_DIMENSION", "32")
            ),
            retrieval_device=os.getenv("RETRIEVAL_DEVICE", "cpu"),
            retrieval_candidate_limit=int(os.getenv("RETRIEVAL_CANDIDATE_LIMIT", "50")),
            retrieval_remote_url=os.getenv("RETRIEVAL_REMOTE_URL") or None,
            retrieval_worker_token=os.getenv("RETRIEVAL_WORKER_TOKEN") or None,
            preference_model_path=os.getenv("PREFERENCE_MODEL_PATH") or None,
        )


def _database_url() -> str:
    if value := os.getenv("DATABASE_URL"):
        return value
    if host := os.getenv("DB_HOST"):
        user = quote_plus(os.getenv("DB_USER", "brandforge"))
        password = quote_plus(os.getenv("DB_PASSWORD", ""))
        port = int(os.getenv("DB_PORT", "5432"))
        name = quote_plus(os.getenv("DB_NAME", "brandforge"))
        return f"postgresql+psycopg://{user}:{password}@{host}:{port}/{name}"
    return "sqlite:///./data/brandforge.db"
