from __future__ import annotations

import base64
import binascii
import hmac

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from brandforge.config import Settings
from brandforge.integrations.clip_scorer import OpenCLIPEmbeddingProvider
from brandforge.retrieval import EmbeddingResult


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class TextEmbeddingRequest(StrictModel):
    text: str = Field(min_length=1, max_length=20_000)


class ImageEmbeddingRequest(StrictModel):
    image_base64: str = Field(min_length=1, max_length=36_000_000)


class EmbeddingResponse(StrictModel):
    vector: list[float]
    model: str
    model_version: str
    dimension: int
    synthetic: bool


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    provider = OpenCLIPEmbeddingProvider(
        model_name=settings.retrieval_model_name,
        pretrained=settings.retrieval_model_version,
        expected_dimension=settings.retrieval_embedding_dimension,
        device=settings.retrieval_device,
    )
    app = FastAPI(
        title="BrandForge multimodal inference",
        docs_url=None,
        redoc_url=None,
    )

    def authorize(authorization: str | None) -> None:
        expected = settings.retrieval_worker_token
        if expected is None:
            return
        supplied = authorization.removeprefix("Bearer ") if authorization else ""
        if not hmac.compare_digest(supplied, expected):
            raise HTTPException(status_code=401, detail="invalid worker token")

    @app.get("/health/live")
    def live() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/v1/embed/text", response_model=EmbeddingResponse)
    def embed_text(
        body: TextEmbeddingRequest,
        authorization: str | None = Header(default=None),
    ) -> EmbeddingResponse:
        authorize(authorization)
        return _response(provider.embed_text(body.text))

    @app.post("/v1/embed/image", response_model=EmbeddingResponse)
    def embed_image(
        body: ImageEmbeddingRequest,
        authorization: str | None = Header(default=None),
    ) -> EmbeddingResponse:
        authorize(authorization)
        try:
            content = base64.b64decode(body.image_base64, validate=True)
        except (binascii.Error, ValueError) as error:
            raise HTTPException(status_code=422, detail="image must be valid base64") from error
        if not content or len(content) > 25 * 1024 * 1024:
            raise HTTPException(status_code=422, detail="image size is outside worker limits")
        if not (
            content.startswith(b"\x89PNG\r\n\x1a\n")
            or content.startswith(b"\xff\xd8\xff")
        ):
            raise HTTPException(status_code=422, detail="image must be PNG or JPEG")
        return _response(provider.embed_image(content))

    return app


def _response(result: EmbeddingResult) -> EmbeddingResponse:
    return EmbeddingResponse(
        vector=list(result.vector),
        model=result.model,
        model_version=result.model_version,
        dimension=result.dimension,
        synthetic=result.synthetic,
    )


app = create_app()
