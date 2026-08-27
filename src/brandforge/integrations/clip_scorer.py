from __future__ import annotations

import base64
import hashlib
import io
import threading
from typing import Any

from ..retrieval import EmbeddingResult, cosine_similarity, normalize_embedding


class OpenCLIPEmbeddingProvider:
    """Lazy optional OpenCLIP adapter supporting CLIP and SigLIP model configurations."""

    def __init__(
        self,
        model_name: str = "ViT-B-32",
        pretrained: str = "laion2b_s34b_b79k",
        *,
        expected_dimension: int | None = None,
        device: str = "cpu",
    ) -> None:
        if not model_name.strip() or not pretrained.strip():
            raise ValueError("model_name and pretrained must be non-empty")
        if expected_dimension is not None and expected_dimension < 1:
            raise ValueError("expected_dimension must be positive")
        if not device.strip():
            raise ValueError("device must be non-empty")
        self._model_name = model_name
        self._pretrained = pretrained
        self._expected_dimension = expected_dimension
        self._dimension: int | None = expected_dimension
        self._device = device
        self._torch: Any = None
        self._pillow_image: Any = None
        self._model: Any = None
        self._preprocess: Any = None
        self._tokenizer: Any = None
        self._load_lock = threading.Lock()

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def model_version(self) -> str:
        return self._pretrained

    @property
    def dimension(self) -> int:
        self._ensure_loaded()
        assert self._dimension is not None
        return self._dimension

    def embed_text(self, text: str) -> EmbeddingResult:
        if not isinstance(text, str) or not text.strip():
            raise ValueError("text must be a non-empty string")
        self._ensure_loaded()
        tokens = self._tokenizer([text]).to(self._device)
        with self._torch.no_grad():
            features = self._model.encode_text(tokens)
        return self._result(features)

    def embed_image(self, image_bytes: bytes) -> EmbeddingResult:
        if not isinstance(image_bytes, bytes) or not image_bytes:
            raise ValueError("image_bytes must be non-empty bytes")
        self._ensure_loaded()
        image = self._pillow_image.open(io.BytesIO(image_bytes)).convert("RGB")
        image_tensor = self._preprocess(image).unsqueeze(0).to(self._device)
        with self._torch.no_grad():
            features = self._model.encode_image(image_tensor)
        return self._result(features)

    def _ensure_loaded(self) -> None:
        if self._model is not None:
            return
        with self._load_lock:
            if self._model is not None:
                return
            # Optional heavyweight packages are deliberately imported only on first use.
            try:
                open_clip = __import__("open_clip")
                torch = __import__("torch")
                pillow_image = __import__("PIL.Image", fromlist=["Image"])
            except ImportError as error:
                raise RuntimeError(
                    "OpenCLIP retrieval requires the optional 'multimodal' dependencies"
                ) from error
            model, _, preprocess = open_clip.create_model_and_transforms(
                self._model_name,
                pretrained=self._pretrained,
                device=self._device,
            )
            model = model.eval()
            tokenizer = open_clip.get_tokenizer(self._model_name)
            dimension = self._infer_dimension(model)
            if self._expected_dimension is not None and dimension != self._expected_dimension:
                raise ValueError(
                    f"OpenCLIP model dimension {dimension} does not match "
                    f"configured dimension {self._expected_dimension}"
                )
            self._torch = torch
            self._pillow_image = pillow_image
            self._model = model
            self._preprocess = preprocess
            self._tokenizer = tokenizer
            self._dimension = dimension

    @staticmethod
    def _infer_dimension(model: Any) -> int:
        text_projection = getattr(model, "text_projection", None)
        shape = getattr(text_projection, "shape", None)
        if shape is None or not shape:
            raise ValueError("unable to determine OpenCLIP embedding dimension")
        dimension = int(shape[-1])
        if dimension < 1:
            raise ValueError("OpenCLIP returned an invalid embedding dimension")
        return dimension

    def _result(self, features: Any) -> EmbeddingResult:
        raw_values = features.detach().to("cpu").reshape(-1).tolist()
        vector = normalize_embedding(tuple(float(value) for value in raw_values))
        dimension = self.dimension
        if len(vector) != dimension:
            raise ValueError(
                f"OpenCLIP returned dimension {len(vector)}, expected {dimension}"
            )
        return EmbeddingResult(
            vector=vector,
            model=self.model_name,
            model_version=self.model_version,
            dimension=dimension,
            synthetic=False,
        )


class DeterministicEmbeddingProvider:
    """Normalized hash embeddings for tests only; never use for production retrieval."""

    def __init__(self, dimension: int = 32, *, seed: str = "brandforge-test") -> None:
        if not 2 <= dimension <= 4096:
            raise ValueError("dimension must be between 2 and 4096")
        if not seed:
            raise ValueError("seed must be non-empty")
        self._dimension = dimension
        self._seed = seed.encode()

    @property
    def model_name(self) -> str:
        return "deterministic-hash-non-production"

    @property
    def model_version(self) -> str:
        return "1"

    @property
    def dimension(self) -> int:
        return self._dimension

    def embed_text(self, text: str) -> EmbeddingResult:
        if not isinstance(text, str) or not text.strip():
            raise ValueError("text must be a non-empty string")
        return self._embed(b"text\0" + text.encode("utf-8"))

    def embed_image(self, image_bytes: bytes) -> EmbeddingResult:
        if not isinstance(image_bytes, bytes) or not image_bytes:
            raise ValueError("image_bytes must be non-empty bytes")
        return self._embed(b"image\0" + image_bytes)

    def _embed(self, payload: bytes) -> EmbeddingResult:
        digest = hashlib.shake_256(self._seed + b"\0" + payload).digest(self._dimension * 2)
        values = tuple(
            (int.from_bytes(digest[index : index + 2], "big") - 32767.5) / 32767.5
            for index in range(0, len(digest), 2)
        )
        vector = normalize_embedding(values)
        return EmbeddingResult(
            vector=vector,
            model=self.model_name,
            model_version=self.model_version,
            dimension=self.dimension,
            synthetic=True,
        )


class RemoteEmbeddingProvider:
    """Thin API-side client for the isolated multimodal inference service."""

    def __init__(
        self,
        *,
        base_url: str,
        model_name: str,
        model_version: str,
        dimension: int,
        token: str | None = None,
        timeout_seconds: float = 30.0,
    ) -> None:
        if not base_url.startswith(("http://", "https://")):
            raise ValueError("remote embedding URL must be absolute HTTP(S)")
        if dimension < 1:
            raise ValueError("remote embedding dimension must be positive")
        self._base_url = base_url.rstrip("/")
        self._model_name = model_name
        self._model_version = model_version
        self._dimension = dimension
        self._token = token
        self._timeout_seconds = timeout_seconds

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def model_version(self) -> str:
        return self._model_version

    @property
    def dimension(self) -> int:
        return self._dimension

    def embed_text(self, text: str) -> EmbeddingResult:
        return self._request("/v1/embed/text", {"text": text})

    def embed_image(self, image_bytes: bytes) -> EmbeddingResult:
        return self._request(
            "/v1/embed/image",
            {"image_base64": base64.b64encode(image_bytes).decode("ascii")},
        )

    def _request(self, path: str, payload: dict[str, str]) -> EmbeddingResult:
        import httpx

        headers = {"Authorization": f"Bearer {self._token}"} if self._token else {}
        with httpx.Client(timeout=self._timeout_seconds) as client:
            response = client.post(self._base_url + path, json=payload, headers=headers)
            response.raise_for_status()
            raw = response.json()
        result = EmbeddingResult(
            vector=tuple(float(value) for value in raw["vector"]),
            model=str(raw["model"]),
            model_version=str(raw["model_version"]),
            dimension=int(raw["dimension"]),
            synthetic=bool(raw.get("synthetic", False)),
        )
        if (
            result.model != self.model_name
            or result.model_version != self.model_version
            or result.dimension != self.dimension
        ):
            raise ValueError("remote embedding identity does not match API configuration")
        return result


class OpenClipScorer:
    """Backward-compatible text-to-image scorer backed by lazy OpenCLIP embeddings."""

    def __init__(
        self,
        model_name: str = "ViT-B-32",
        pretrained: str = "laion2b_s34b_b79k",
    ) -> None:
        self.provider = OpenCLIPEmbeddingProvider(
            model_name=model_name,
            pretrained=pretrained,
        )

    def score(self, text: str, image_bytes: bytes) -> float:
        text_embedding = self.provider.embed_text(text)
        image_embedding = self.provider.embed_image(image_bytes)
        similarity = cosine_similarity(text_embedding.vector, image_embedding.vector)
        return max(0.0, min(1.0, (float(similarity) + 1.0) / 2.0))
