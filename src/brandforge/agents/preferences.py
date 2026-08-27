from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ..domain import ScoreBreakdown

FEATURES = (
    "brief_alignment",
    "visual_alignment",
    "copy_image_consistency",
    "visual_quality",
    "brand_compliance",
    "accessibility",
    "claims_safety",
)


@dataclass(slots=True)
class PairwiseExample:
    preferred: ScoreBreakdown
    rejected: ScoreBreakdown
    weight: float = 1.0

    def __post_init__(self) -> None:
        if not math.isfinite(self.weight) or self.weight <= 0:
            raise ValueError("pairwise example weight must be finite and positive")


@dataclass(slots=True)
class PairwisePreferenceModel:
    """Tiny Bradley-Terry style model for reviewed pairwise campaign feedback."""

    weights: dict[str, float] = field(
        default_factory=lambda: {
            "brief_alignment": 0.8,
            "visual_alignment": 0.6,
            "copy_image_consistency": 0.5,
            "visual_quality": 0.6,
            "brand_compliance": 1.0,
            "accessibility": 0.4,
            "claims_safety": 0.7,
        }
    )
    model_version: str = "preference-v1-untrained"
    training_examples: int = 0
    artifact_schema_version: int = 1
    dataset_fingerprint: str | None = None
    split_fingerprint: str | None = None
    trained_at: str | None = None
    training_hyperparameters: dict[str, float | int] = field(default_factory=dict)

    def fit(
        self,
        examples: list[PairwiseExample],
        *,
        learning_rate: float = 0.08,
        epochs: int = 250,
        l2: float = 0.01,
        dataset_fingerprint: str | None = None,
        split_fingerprint: str | None = None,
    ) -> PairwisePreferenceModel:
        if not math.isfinite(learning_rate) or learning_rate <= 0:
            raise ValueError("learning_rate must be finite and positive")
        if not 1 <= epochs <= 100_000:
            raise ValueError("epochs must be between 1 and 100000")
        if not math.isfinite(l2) or l2 < 0:
            raise ValueError("l2 must be finite and non-negative")
        _validate_fingerprint(dataset_fingerprint, "dataset_fingerprint")
        _validate_fingerprint(split_fingerprint, "split_fingerprint")
        if not examples:
            return self
        for _ in range(epochs):
            gradient = {feature: 0.0 for feature in FEATURES}
            for example in examples:
                difference = {
                    feature: getattr(example.preferred, feature)
                    - getattr(example.rejected, feature)
                    for feature in FEATURES
                }
                probability = _sigmoid(
                    sum(self.weights[feature] * difference[feature] for feature in FEATURES)
                )
                error = (1.0 - probability) * example.weight
                for feature in FEATURES:
                    gradient[feature] += error * difference[feature]
            for feature in FEATURES:
                update = gradient[feature] / len(examples) - l2 * self.weights[feature]
                self.weights[feature] += learning_rate * update
                if not math.isfinite(self.weights[feature]):
                    raise ValueError("preference training produced non-finite weights")
        self.training_examples = len(examples)
        self.dataset_fingerprint = dataset_fingerprint
        self.split_fingerprint = split_fingerprint
        self.trained_at = datetime.now(UTC).isoformat()
        self.training_hyperparameters = {
            "learning_rate": learning_rate,
            "epochs": epochs,
            "l2": l2,
        }
        weight_fingerprint = _fingerprint(self.weights)[:10]
        self.model_version = f"preference-v2-n{len(examples)}-{weight_fingerprint}"
        return self

    def predict(self, scores: ScoreBreakdown) -> float:
        value = sum(self.weights[feature] * getattr(scores, feature) for feature in FEATURES)
        normalizer = sum(abs(weight) for weight in self.weights.values()) or 1.0
        return _sigmoid(4 * (value / normalizer - 0.5))

    def predict_pair(
        self,
        preferred: ScoreBreakdown,
        rejected: ScoreBreakdown,
    ) -> float:
        difference = sum(
            self.weights[feature]
            * (getattr(preferred, feature) - getattr(rejected, feature))
            for feature in FEATURES
        )
        return _sigmoid(difference)

    def save(self, path: str | Path) -> None:
        Path(path).write_text(
            json.dumps(
                {
                    "artifact_schema_version": self.artifact_schema_version,
                    "features": list(FEATURES),
                    "weights": self.weights,
                    "model_version": self.model_version,
                    "training_examples": self.training_examples,
                    "dataset_fingerprint": self.dataset_fingerprint,
                    "split_fingerprint": self.split_fingerprint,
                    "trained_at": self.trained_at,
                    "training_hyperparameters": self.training_hyperparameters,
                },
                indent=2,
                sort_keys=True,
            )
            + "\n"
        )

    @classmethod
    def load(cls, path: str | Path) -> PairwisePreferenceModel:
        raw = json.loads(Path(path).read_text())
        if not isinstance(raw, dict) or raw.get("artifact_schema_version") != 1:
            raise ValueError("unsupported preference model artifact schema")
        if tuple(raw.get("features", ())) != FEATURES:
            raise ValueError("preference model feature schema does not match")
        weights = raw.get("weights")
        if not isinstance(weights, dict) or set(weights) != set(FEATURES):
            raise ValueError("preference model weights are invalid")
        normalized_weights = {feature: float(weights[feature]) for feature in FEATURES}
        if any(not math.isfinite(value) for value in normalized_weights.values()):
            raise ValueError("preference model weights must be finite")
        training_examples = raw.get("training_examples")
        if not isinstance(training_examples, int) or training_examples < 0:
            raise ValueError("preference model training_examples is invalid")
        hyperparameters = raw.get("training_hyperparameters", {})
        if not isinstance(hyperparameters, dict):
            raise ValueError("preference model hyperparameters are invalid")
        if any(
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(float(value))
            for value in hyperparameters.values()
        ):
            raise ValueError("preference model hyperparameters must be finite numbers")
        dataset_fingerprint = _optional_text(raw.get("dataset_fingerprint"))
        split_fingerprint = _optional_text(raw.get("split_fingerprint"))
        _validate_fingerprint(dataset_fingerprint, "dataset_fingerprint")
        _validate_fingerprint(split_fingerprint, "split_fingerprint")
        model = cls(
            weights=normalized_weights,
            model_version=str(raw["model_version"]),
            training_examples=training_examples,
            artifact_schema_version=1,
            dataset_fingerprint=dataset_fingerprint,
            split_fingerprint=split_fingerprint,
            trained_at=_optional_text(raw.get("trained_at")),
            training_hyperparameters={
                str(key): value for key, value in hyperparameters.items()
            },
        )
        return model


def _sigmoid(value: float) -> float:
    if value >= 0:
        return 1 / (1 + math.exp(-value))
    exponential = math.exp(value)
    return exponential / (1 + exponential)


def _fingerprint(value: Any) -> str:
    import hashlib

    return hashlib.sha256(
        json.dumps(value, separators=(",", ":"), sort_keys=True).encode("utf-8")
    ).hexdigest()


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError("preference model metadata text is invalid")
    return value


def _validate_fingerprint(value: str | None, name: str) -> None:
    if value is None:
        return
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError(f"{name} must be a lowercase SHA-256 digest")
